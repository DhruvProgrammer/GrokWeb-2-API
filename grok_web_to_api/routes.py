"""FastAPI routes - OpenAI-compatible surface.

The handler functions are intentionally small; all the heavy lifting
lives in the client and the model classes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from .client import GrokClient, GrokError
from .models import (
    ChatRequest,
    ChatResponse,
    Choice,
    ErrorDetail,
    ErrorResponse,
    ModelsResponse,
    ResponseMessage,
    StreamChunk,
    StreamChoice,
    StreamDelta,
    default_model_list,
    is_valid_model,
    map_model,
    new_chunk_id,
    now,
)

log = logging.getLogger(__name__)


def make_router() -> APIRouter:
    """Build a router. Routes resolve client and limiter via app.state."""
    router = APIRouter()

    # ---- /health ---------------------------------------------------------

    @router.get("/health")
    async def health(request: Request) -> JSONResponse:
        cfg = request.app.state.settings
        if not cfg.is_configured:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "degraded",
                    "reason": f"missing config: {', '.join(cfg.missing_fields)}",
                    "help": "see README - extract cookies and run scripts/extract-challenge.js",
                },
            )
        ok, reason = await request.app.state.grok_client.health()
        if not ok:
            return JSONResponse(status_code=503, content={"status": "degraded", "reason": reason})
        return JSONResponse(status_code=200, content={"status": "ok"})

    # ---- / -------------------------------------------------------------

    @router.get("/")
    async def root() -> dict:
        return {
            "name": "grok-web-to-api",
            "version": "1.0.0",
            "docs": "https://github.com/yourusername/grok-web-to-api#api-endpoints",
            "endpoints": [
                "GET  /health",
                "GET  /v1/models",
                "POST /v1/chat/completions",
                "POST /v1/completions (legacy)",
            ],
        }

    # ---- /v1/models -----------------------------------------------------

    @router.get("/v1/models", response_model=ModelsResponse)
    async def list_models() -> ModelsResponse:
        return ModelsResponse(object="list", data=default_model_list())

    @router.get("/v1/models/{model_id}", response_model=Any)
    async def get_model(model_id: str) -> Any:
        for m in default_model_list():
            if m.id == model_id:
                return m
        raise HTTPException(
            status_code=404,
            detail=ErrorResponse(
                error=ErrorDetail(
                    message=f"model {model_id!r} not found",
                    type="invalid_request_error",
                    code="model_not_found",
                )
            ).model_dump(),
        )

    # ---- /v1/chat/completions ------------------------------------------

    @router.post("/v1/chat/completions")
    async def chat_completions(request: Request, body: ChatRequest) -> Any:
        settings = request.app.state.settings
        if settings.rate_limit_enabled:
            ip = request.client.host if request.client else "unknown"
            allowed, retry = request.app.state.limiter.check(ip)
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content=ErrorResponse(
                        error=ErrorDetail(
                            message="rate limit exceeded; retry shortly",
                            type="rate_limit_error",
                        )
                    ).model_dump(),
                    headers={"Retry-After": str(retry)},
                )

        # Validate.
        err = _validate_chat(body)
        if err is not None:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(error=ErrorDetail(message=err, type="invalid_request_error")).model_dump(),
            )

        prompt = _flatten_messages(body.messages)
        model = map_model(body.model)
        client = request.app.state.grok_client

        if body.stream:
            return StreamingResponse(
                _stream_chat(client, model, prompt, body.model),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # Non-streaming: collect all deltas, then emit one response.
        try:
            chunks: list[str] = []
            async for delta in client.chat(model, prompt):
                chunks.append(delta)
            content = "".join(chunks)
        except GrokError as e:
            return JSONResponse(
                status_code=502,
                content=ErrorResponse(
                    error=ErrorDetail(message=f"upstream error: {e}", type="upstream_error")
                ).model_dump(),
            )

        return ChatResponse(
            id=new_chunk_id(),
            created=now(),
            model=body.model,
            choices=[
                Choice(
                    message=ResponseMessage(role="assistant", content=content),
                    finish_reason="stop",
                )
            ],
        )

    # ---- /v1/completions (legacy) --------------------------------------

    @router.post("/v1/completions")
    async def legacy_completions(request: Request) -> Any:
        """Legacy text-davinci-003 style endpoint.

        Converted to a single user turn internally.
        """
        try:
            raw = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error=ErrorDetail(message="invalid JSON", type="invalid_request_error")
                ).model_dump(),
            )

        prompt = raw.get("prompt")
        if prompt is None:
            return JSONResponse(
                status_code=400,
                content=ErrorResponse(
                    error=ErrorDetail(message="prompt is required", type="invalid_request_error")
                ).model_dump(),
            )

        body = ChatRequest(
            model=raw.get("model") or "grok-auto",
            messages=[{"role": "user", "content": prompt}],
            stream=bool(raw.get("stream")),
        )
        # Recurse through the chat handler.
        return await chat_completions(request, body)

    return router


# ---------- Helpers ----------


def _validate_chat(body: ChatRequest) -> str | None:
    """Return None on success, otherwise an error message."""
    if not body.model:
        return "model is required"
    if not is_valid_model(body.model):
        return "model not supported (allowed: grok-auto, grok-4, grok-4-fast, grok-3, grok-3-mini, grok-2, grok-2-mini)"
    if not body.messages:
        return "messages must not be empty"
    return None


def _flatten_messages(messages) -> str:
    """Concatenate OpenAI-style messages into one prompt.

    The grok.com web client doesn't maintain server-side conversation
    state the same way the OpenAI API does, so we fold the whole thread
    into a single user turn with role markers.
    """
    out = []
    for m in messages:
        role = m.role.upper()
        content = m.content
        if isinstance(content, list):
            content = "\n".join(str(p) for p in content)
        elif content is None:
            content = ""
        out.append(f"[{role}]\n{content}")
    return "\n\n".join(out) + "\n\n"


async def _stream_chat(client: GrokClient, model: str, prompt: str, req_model: str):
    """Async generator that yields SSE frames in OpenAI's chunk format."""
    chunk_id = new_chunk_id()
    created = now()

    # First chunk: role only, no content.
    first = StreamChunk(
        id=chunk_id,
        created=created,
        model=req_model,
        choices=[StreamChoice(index=0, delta=StreamDelta(role="assistant"))],
    )
    yield _sse_frame(first.model_dump(exclude_none=True))

    # Subsequent chunks: content deltas.
    try:
        async for delta in client.chat(model, prompt):
            ch = StreamChunk(
                id=chunk_id,
                created=created,
                model=req_model,
                choices=[StreamChoice(index=0, delta=StreamDelta(content=delta))],
            )
            yield _sse_frame(ch.model_dump(exclude_none=True))
            # Cooperative yield so cancellation can take effect between chunks.
            await asyncio.sleep(0)
    except GrokError as e:
        # We can't change status code after the response started, so
        # emit a sentinel frame and let the client disconnect.
        err_chunk = {
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": req_model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "error": {"message": str(e), "type": "upstream_error"},
        }
        yield _sse_frame(err_chunk)

    # Final chunk: finish_reason only.
    final = StreamChunk(
        id=chunk_id,
        created=created,
        model=req_model,
        choices=[StreamChoice(index=0, delta=StreamDelta(), finish_reason="stop")],
    )
    yield _sse_frame(final.model_dump(exclude_none=True))
    yield "data: [DONE]\n\n"


def _sse_frame(payload: dict) -> str:
    """One SSE event in the standard `data: <json>\\n\\n` form."""
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"