"""Pydantic models for OpenAI-compatible wire format.

We keep the surface area small and explicit so the wire format is obvious.
Anything not declared here is silently ignored on the way in and never
emitted on the way out.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ---------- Request models ----------


class ChatMessage(BaseModel):
    """One turn in the conversation. Content may be a string or list."""

    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: Union[str, List[Any], None] = None
    name: Optional[str] = None


class ChatRequest(BaseModel):
    """Body of POST /v1/chat/completions."""

    model_config = ConfigDict(extra="ignore")

    model: str
    messages: List[ChatMessage]
    stream: bool = False

    # Optional fields accepted but not forwarded to grok.com.
    # The web client doesn't expose temperature/top_p/... so we capture
    # them here to keep clients that send them by default happy.
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    stop: Optional[Union[str, List[str]]] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    user: Optional[str] = None


# ---------- Response models ----------


class Usage(BaseModel):
    """Token usage. Always zero because grok.com does not expose counts."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ResponseMessage(BaseModel):
    role: str = "assistant"
    content: str = ""


class Choice(BaseModel):
    index: int = 0
    message: ResponseMessage
    finish_reason: str = "stop"


class ChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Choice]
    usage: Usage = Field(default_factory=Usage)


# ---------- Streaming models ----------


class StreamDelta(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: StreamDelta
    finish_reason: Optional[str] = None


class StreamChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[StreamChoice]


# ---------- Model catalog ----------


class ModelInfo(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "xai"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: List[ModelInfo]


# ---------- Error envelope ----------


class ErrorDetail(BaseModel):
    message: str
    type: str
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ---------- Helpers ----------


# Friendly model name -> Grok internal model id. Unknown values fall
# back to "auto" so the web UI still picks something sensible.
_MODEL_MAP = {
    "grok-auto": "auto",
    "auto": "auto",
    "grok-4": "grok-4",
    "grok-4-fast": "grok-4-fast",
    "grok-3": "grok-3",
    "grok-3-mini": "grok-3-mini",
    "grok-2": "grok-2",
    "grok-2-mini": "grok-2-mini",
}


def map_model(name: str) -> str:
    """Translate an OpenAI-style model name to Grok's internal id."""
    return _MODEL_MAP.get(name, "auto")


def is_valid_model(name: str) -> bool:
    return name in _MODEL_MAP


def now() -> int:
    return int(time.time())


def new_chunk_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


# Curated model catalog shown by /v1/models. Order matters: most-used first.
def default_model_list() -> List[ModelInfo]:
    t = now()
    return [
        ModelInfo(id="grok-auto", created=t, owned_by="xai"),
        ModelInfo(id="grok-4", created=t, owned_by="xai"),
        ModelInfo(id="grok-4-fast", created=t, owned_by="xai"),
        ModelInfo(id="grok-3", created=t, owned_by="xai"),
        ModelInfo(id="grok-3-mini", created=t, owned_by="xai"),
        ModelInfo(id="grok-2", created=t, owned_by="xai"),
        ModelInfo(id="grok-2-mini", created=t, owned_by="xai"),
    ]