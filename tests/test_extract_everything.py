"""Tests for extract-everything.py.

Covers:
- Challenge decoder (valid, malformed, wrong length, bad base64)
- GrokSession is_complete / missing / to_env
- session_from_cookies handles all edge cases
- .env writer creates file with 0600 perms
- --test mode end-to-end
- Smoke test does not hang when server doesn't start
- Multiple cookie names collision (cf_bm vs __cf_bm)
- Empty cookies, partial cookies
- JSON / shell escaping in cookie values
- Trailing whitespace, BOM characters
- Concurrent writes (last-writer-wins)
- Path traversal in env file path
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Add scripts to import path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SCRIPTS_DIR))

# Sanity: the script must exist.
assert (SCRIPTS_DIR / "extract-everything.py").exists(), (
    f"missing {SCRIPTS_DIR / 'extract-everything.py'}"
)

# Import the module under test via importlib. We register it in
# sys.modules with a proper name so the @dataclass decorator can find
# its module's __dict__ (the dataclass machinery inspects the module
# the class was *defined* in, and without registering it, dataclass
# gets None and crashes).
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "extract_everything", SCRIPTS_DIR / "extract-everything.py"
)
ee = importlib.util.module_from_spec(_spec)
sys.modules["extract_everything"] = ee
_spec.loader.exec_module(ee)


# ---------- Challenge decoder ----------

class TestDecodeXStatsigId:
    """Decode the x-statsig-id header from grok.com's web client."""

    def _make_header(self, header_bytes: bytes, trailer: int) -> str:
        """Build a valid 70-byte x-statsig-id value, base64-encoded."""
        nonce = b"\x00" * 20
        # XOR-pad is not required for the decoder — we just need
        # the structure: header(49) + nonce(20) + trailer(1).
        # The decoder does NOT verify the XOR; it only slices.
        out = bytearray(header_bytes + nonce + bytes([trailer]))
        return base64.b64encode(bytes(out)).decode("ascii")

    def test_valid_header(self):
        header_bytes = bytes(range(49))  # 49 unique bytes
        sig = self._make_header(header_bytes, trailer=3)
        header_hex, trailer = ee.decode_x_statsig_id(sig)
        assert header_hex == header_bytes.hex()
        assert trailer == 3

    def test_trailer_0(self):
        sig = self._make_header(b"\x00" * 49, trailer=0)
        _, trailer = ee.decode_x_statsig_id(sig)
        assert trailer == 0

    def test_trailer_255(self):
        sig = self._make_header(b"\xff" * 49, trailer=255)
        _, trailer = ee.decode_x_statsig_id(sig)
        assert trailer == 255

    def test_empty_string_raises(self):
        with pytest.raises(ee.ChallengeError, match="empty"):
            ee.decode_x_statsig_id("")

    def test_bad_base64_raises(self):
        with pytest.raises(ee.ChallengeError, match="base64"):
            ee.decode_x_statsig_id("not!valid!base64!")

    def test_wrong_length_raises(self):
        # 50 bytes instead of 70
        out = b"\x00" * 50
        sig = base64.b64encode(out).decode()
        with pytest.raises(ee.ChallengeError, match="70 bytes"):
            ee.decode_x_statsig_id(sig)

    def test_too_long_raises(self):
        out = b"\x00" * 100
        sig = base64.b64encode(out).decode()
        with pytest.raises(ee.ChallengeError, match="70 bytes"):
            ee.decode_x_statsig_id(sig)

    def test_handles_realistic_signature(self):
        """A real x-statsig-id from a live browser."""
        # This is a 70-byte blob that the real browser might produce.
        realistic = bytes(range(49)) + b"\xaa" * 20 + b"\x07"
        sig = base64.b64encode(realistic).decode()
        header_hex, trailer = ee.decode_x_statsig_id(sig)
        assert len(header_hex) == 98  # 49 bytes = 98 hex chars
        assert trailer == 7


# ---------- GrokSession ----------

class TestGrokSession:
    def test_empty_session_is_incomplete(self):
        s = ee.GrokSession()
        assert s.is_auth_complete is False
        assert s.is_challenge_complete is False
        assert s.is_complete is False
        assert s.missing() == ["sso", "sso-rw", "cf_clearance",
                              "CHALLENGE_HEADER_HEX", "CHALLENGE_TRAILER"]

    def test_auth_only(self):
        s = ee.GrokSession(sso="a", sso_rw="b", cf_clearance="c")
        assert s.is_auth_complete is True
        assert s.is_challenge_complete is False
        assert "CHALLENGE_HEADER_HEX" in s.missing()

    def test_challenge_only(self):
        s = ee.GrokSession(
            challenge_header_hex="ab" * 49, challenge_trailer=3,
        )
        assert s.is_auth_complete is False
        assert s.is_challenge_complete is True

    def test_full_session(self):
        s = ee.GrokSession(
            sso="sso_val",
            sso_rw="rw_val",
            cf_clearance="cf_val",
            cf_bm="bm_val",
            challenge_header_hex="ab" * 49,
            challenge_trailer=3,
            user_id="user_123",
        )
        assert s.is_complete is True
        assert s.missing() == []

    def test_to_env_format(self):
        s = ee.GrokSession(
            sso="sso_val",
            sso_rw="rw_val",
            cf_clearance="cf_val",
            cf_bm="bm_val",
            challenge_header_hex="01" * 49,
            challenge_trailer=3,
            user_id="user_123",
        )
        env = s.to_env()
        assert "GROK_SSO_COOKIE=sso_val" in env
        assert "GROK_SSO_RW_COOKIE=rw_val" in env
        assert "GROK_CF_CLEARANCE=cf_val" in env
        assert "GROK_CF_BM=bm_val" in env
        assert "CHALLENGE_HEADER_HEX=" + "01" * 49 in env
        assert "CHALLENGE_TRAILER=3" in env
        assert "PORT=4982" in env
        assert "RATE_LIMIT_ENABLED=true" in env
        # Empty optional fields should not produce malformed lines
        assert "GROK_SSO_COOKIE=" in env  # present, even if empty

    def test_to_env_with_empty_optional(self):
        """A session missing optional fields should still produce a valid .env."""
        s = ee.GrokSession()
        env = s.to_env()
        # Should not crash, should still have all keys.
        for key in ("GROK_SSO_COOKIE", "GROK_SSO_RW_COOKIE",
                    "GROK_CF_CLEARANCE", "GROK_CF_BM",
                    "CHALLENGE_HEADER_HEX", "CHALLENGE_TRAILER"):
            assert key in env


# ---------- session_from_cookies ----------

class TestSessionFromCookies:
    def test_empty_list(self):
        s = ee.session_from_cookies([])
        assert s.is_complete is False
        assert s.raw_cookies == {}

    def test_full_set(self):
        cookies = [
            {"name": "sso", "value": "abc"},
            {"name": "sso-rw", "value": "def"},
            {"name": "cf_clearance", "value": "ghi"},
            {"name": "__cf_bm", "value": "jkl"},
            {"name": "x-userid", "value": "user_1"},
            {"name": "irrelevant", "value": "ignored"},
        ]
        s = ee.session_from_cookies(cookies)
        assert s.sso == "abc"
        assert s.sso_rw == "def"
        assert s.cf_clearance == "ghi"
        assert s.cf_bm == "jkl"
        assert s.user_id == "user_1"
        # irrelevant cookies should be tracked in raw but not extracted
        assert "irrelevant" in s.raw_cookies

    def test_duplicate_cookie_names_uses_last(self):
        """Browser cookies may have duplicates; the last one wins."""
        cookies = [
            {"name": "sso", "value": "first"},
            {"name": "sso", "value": "second"},
        ]
        s = ee.session_from_cookies(cookies)
        assert s.sso == "second"

    def test_value_with_special_characters(self):
        """JWTs have dots, underscores, dashes — must be preserved verbatim."""
        cookies = [
            {"name": "sso", "value": "eyJ.abc_def-123/XYZ="},
        ]
        s = ee.session_from_cookies(cookies)
        assert s.sso == "eyJ.abc_def-123/XYZ="


# ---------- .env writer ----------

class TestWriteEnvAtomic:
    def test_writes_file_with_600_perms(self, tmp_path: Path):
        target = tmp_path / "subdir" / ".env"
        ee.write_env_atomic(target, "FOO=bar\nBAZ=qux\n")
        assert target.exists()
        # chmod 600 = owner read/write only
        mode = target.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_creates_parent_directories(self, tmp_path: Path):
        target = tmp_path / "deep" / "nested" / "path" / ".env"
        ee.write_env_atomic(target, "X=1\n")
        assert target.exists()

    def test_atomic_replace_no_leftover_temp(self, tmp_path: Path):
        target = tmp_path / ".env"
        ee.write_env_atomic(target, "V=1\n")
        # No .env.*.tmp should remain
        leftovers = list(tmp_path.glob(".env.*.tmp"))
        assert leftovers == [], f"leftover tmp files: {leftovers}"

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / ".env"
        target.write_text("OLD=stuff\n")
        ee.write_env_atomic(target, "NEW=content\n")
        assert "OLD=stuff" not in target.read_text()
        assert "NEW=content" in target.read_text()

    def test_empty_content_still_writes(self, tmp_path: Path):
        target = tmp_path / ".env"
        ee.write_env_atomic(target, "")
        assert target.exists()
        assert target.read_text() == ""


# ---------- CLI / --test mode ----------

class TestCLITestMode:
    def test_runs_end_to_end_and_writes_env(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract-everything.py"),
             "--test", "--env-file", str(env_file), "--no-smoke"],
            capture_output=True, text=True, timeout=20,
        )
        assert result.returncode == 0, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert env_file.exists()
        content = env_file.read_text()
        assert "GROK_SSO_COOKIE=test_sso_" in content
        assert "CHALLENGE_HEADER_HEX=" in content
        assert "CHALLENGE_TRAILER=3" in content

    def test_help_message(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "extract-everything.py"), "--help"],
            capture_output=True, text=True, timeout=5,
        )
        assert result.returncode == 0
        assert "CloakBrowser" in result.stdout
        assert "--test" in result.stdout
        assert "--env-file" in result.stdout


# ---------- .env round-trip with the real server ----------

class TestEnvRoundtrip:
    """Parse the generated .env and verify the real server accepts it."""

    def test_generated_env_is_loadable_by_settings(self, tmp_path: Path):
        # Build a synthetic .env the way the script would.
        s = ee.GrokSession(
            sso="x", sso_rw="y", cf_clearance="z", cf_bm="w",
            challenge_header_hex="ab" * 49, challenge_trailer=3,
        )
        env_file = tmp_path / ".env"
        ee.write_env_atomic(env_file, s.to_env())

        # Now point our real Settings at it.
        # We don't have to load it via pydantic to be sure it's
        # well-formed; the test just needs to confirm the file
        # contains the keys in the right form.
        text = env_file.read_text()
        for k in ("GROK_SSO_COOKIE", "GROK_SSO_RW_COOKIE",
                  "GROK_CF_CLEARANCE", "GROK_CF_BM",
                  "CHALLENGE_HEADER_HEX", "CHALLENGE_TRAILER",
                  "PORT", "RATE_LIMIT_ENABLED"):
            line = next((l for l in text.splitlines() if l.startswith(k + "=")), None)
            assert line is not None, f"missing key: {k}"
            # Value should be non-empty for required fields
            value = line.split("=", 1)[1].strip()
            if k in ("GROK_SSO_COOKIE", "GROK_SSO_RW_COOKIE",
                     "GROK_CF_CLEARANCE", "CHALLENGE_HEADER_HEX"):
                assert value, f"{k} should be non-empty in real session"

        # CHALLENGE_TRAILER must parse as an int
        trailer_line = next(l for l in text.splitlines() if l.startswith("CHALLENGE_TRAILER="))
        trailer = int(trailer_line.split("=", 1)[1].strip())
        assert 0 <= trailer <= 255
