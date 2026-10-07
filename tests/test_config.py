"""Tests for the Settings config object."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from grok_web_to_api.config import Settings


def test_minimal_config_loads():
    """Without any env vars, settings still load with defaults."""
    # Reset any cached settings.
    with patch.dict(os.environ, {}, clear=True):
        s = Settings(_env_file=None)
        assert s.port == 4982
        assert s.grok_base_url == "https://grok.com"
        assert s.rate_limit_enabled is True


def test_trailer_must_be_byte():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValidationError):
            Settings(challenge_trailer=256, _env_file=None)
        with pytest.raises(ValidationError):
            Settings(challenge_trailer=-1, _env_file=None)


def test_is_configured_requires_all_three():
    with patch.dict(os.environ, {}, clear=True):
        s = Settings(_env_file=None)
        assert s.is_configured is False
        assert "GROK_SSO_COOKIE" in s.missing_fields
        assert "GROK_SSO_RW_COOKIE" in s.missing_fields
        assert "CHALLENGE_HEADER_HEX" in s.missing_fields


def test_is_configured_when_all_set():
    with patch.dict(os.environ, {}, clear=True):
        s = Settings(
            grok_sso_cookie="x",
            grok_sso_rw_cookie="y",
            challenge_header_hex="00" * 49,
            _env_file=None,
        )
        assert s.is_configured is True
        assert s.missing_fields == []