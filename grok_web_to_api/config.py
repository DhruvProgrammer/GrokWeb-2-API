"""Configuration loaded from environment variables.

The settings object is created once at startup; `get_settings()` returns the
same instance for the life of the process so tests can monkey-patch env vars
between cases.
"""

from __future__ import annotations

import logging
import sys
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    """All runtime configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Server.
    host: str = "0.0.0.0"
    port: int = 4982
    log_level: str = "INFO"

    # Cookie auth (required).
    grok_sso_cookie: str = ""
    grok_sso_rw_cookie: str = ""
    # Cloudflare clearance (required for non-browser requests).
    # cf_clearance is the post-challenge token; cf_bm is the bot-mgmt cookie.
    # Both expire (cf_clearance ~30min, cf_bm ~30min) and need to be refreshed
    # by re-loading grok.com in a browser.
    grok_cf_clearance: str = ""
    grok_cf_bm: str = ""

    # Anti-bot challenge (required).
    challenge_header_hex: str = ""
    challenge_trailer: int = 3

    # Behaviour.
    grok_temporary: bool = True
    grok_base_url: str = "https://grok.com"
    grok_origin: str = "https://grok.com"
    grok_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    # Rate limiting.
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_max_requests: int = 20

    # Request timeouts (seconds).
    request_timeout: float = 120.0
    health_timeout: float = 5.0

    # Field-level validation: trailer must fit in a single byte.
    @field_validator("challenge_trailer")
    @classmethod
    def _trailer_in_range(cls, v: int) -> int:
        if not 0 <= v <= 255:
            raise ValueError("challenge_trailer must be between 0 and 255")
        return v

    @property
    def is_configured(self) -> bool:
        """True when the minimum required auth is set."""
        return bool(
            self.grok_sso_cookie
            and self.grok_sso_rw_cookie
            and self.challenge_header_hex
            and self.grok_cf_clearance
        )

    @property
    def missing_fields(self) -> List[str]:
        """List of env vars that are still required before startup."""
        out: List[str] = []
        if not self.grok_sso_cookie:
            out.append("GROK_SSO_COOKIE")
        if not self.grok_sso_rw_cookie:
            out.append("GROK_SSO_RW_COOKIE")
        if not self.challenge_header_hex:
            out.append("CHALLENGE_HEADER_HEX")
        if not self.grok_cf_clearance:
            out.append("GROK_CF_CLEARANCE")
        return out


# Module-level singleton. Tests that need a fresh settings object should
# clear `get_settings.cache_info()` and call again after mutating env vars.
_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide settings, creating it on first call."""
    global _settings
    if _settings is None:
        _settings = Settings()
        if not _settings.is_configured:
            missing = ", ".join(_settings.missing_fields)
            log.warning(
                "missing required env vars: %s. "
                "The server will start but /v1/* will fail until these are set. "
                "See README for setup.",
                missing,
            )
    return _settings


def validate_or_exit(settings: Settings) -> None:
    """Print a helpful error and exit if the config is incomplete.

    Used in production startup; tests skip this and rely on the
    `degraded` health response instead.
    """
    if settings.is_configured:
        return
    missing = ", ".join(settings.missing_fields)
    sys.stderr.write(
        f"\n[config] missing required env vars: {missing}\n"
        "Run scripts/extract-challenge.js in grok.com DevTools to fill them, "
        "then paste into .env (see README).\n\n"
    )
    sys.exit(1)