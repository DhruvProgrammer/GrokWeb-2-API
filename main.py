"""Entry point: `python main.py` or `uvicorn main:app`.

Reads config from .env / env vars and starts uvicorn with sane
defaults. Use `validate_or_exit` so the user gets a clear message
when SSO cookies or the challenge are absent.
"""

from __future__ import annotations

import logging
import os
import sys

import uvicorn

# Make sure we can `import grok_web_to_api` when run from the project root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from grok_web_to_api.config import get_settings, validate_or_exit
from grok_web_to_api.server import create_app


# Module-level app so `uvicorn main:app` works.
# config is loaded lazily so importing main.py doesn't require all env vars
# (only running it does).
app = create_app(get_settings())


def main() -> None:
    settings = get_settings()
    validate_or_exit(settings)

    log = logging.getLogger("main")
    log.info("starting uvicorn on %s:%d", settings.host, settings.port)

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        access_log=True,
    )


if __name__ == "__main__":
    main()