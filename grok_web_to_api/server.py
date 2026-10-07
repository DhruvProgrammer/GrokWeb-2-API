"""FastAPI app factory.

`create_app()` wires the client, limiter, and routes into a fresh
ASGI app. Tests use this directly via httpx.AsyncClient.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .challenge import ChallengeSigner
from .client import GrokClient
from .config import Settings, get_settings
from .models import ErrorDetail, ErrorResponse
from .rate_limit import RateLimiter
from .routes import make_router


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a configured FastAPI app."""
    cfg = settings or get_settings()
    _setup_logging(cfg.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: lifespan is the right place to wire async resources.
        # But we also populate state eagerly below so tests that
        # short-circuit the lifespan still see the routes work.
        try:
            yield
        finally:
            # Close the httpx client if lifespan actually ran.
            client = getattr(app.state, "grok_client", None)
            if client is not None:
                await client.aclose()

    app = FastAPI(
        title="Grok Web To API",
        version="1.0.0",
        description="Reverse-engineered OpenAI-compatible API for grok.com",
        lifespan=lifespan,
    )

    # CORS: open by default since this is a local proxy. Lock down via
    # reverse proxy if you expose it publicly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
        max_age=43200,
    )

    # Populate app.state eagerly so routes have a client to talk to
    # the moment the app is constructed. lifespan() above only handles
    # clean shutdown of the httpx pool.
    if cfg.is_configured:
        try:
            signer = ChallengeSigner.from_hex(cfg.challenge_header_hex, cfg.challenge_trailer)
        except ValueError as e:
            logging.error("challenge signer: %s", e)
            raise
        logging.info("challenge signer ready: %s", signer.summary())
    else:
        signer = ChallengeSigner.from_hex("00" * 49, 3)
        logging.warning("running without challenge config; /v1/* will return 503")

    app.state.settings = cfg
    app.state.signer = signer
    app.state.grok_client = GrokClient(cfg, signer)
    app.state.limiter = RateLimiter(
        window_seconds=cfg.rate_limit_window_seconds,
        max_requests=cfg.rate_limit_max_requests,
    )

    # Register routes eagerly. They read live client/limiter from
    # request.app.state at request time, so re-populating state in
    # lifespan() would still work for production (where we want async
    # cleanup of the httpx pool).
    app.include_router(make_router())

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        logging.exception("unhandled exception in %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorDetail(
                    message=f"internal error: {exc.__class__.__name__}",
                    type="server_error",
                )
            ).model_dump(),
        )

    return app