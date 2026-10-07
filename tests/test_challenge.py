"""Tests for the x-statsig-id signer."""

from __future__ import annotations

import base64
import string

import pytest

from grok_web_to_api.challenge import ChallengeSigner


# 49 bytes == 98 hex characters.
VALID_HEX = "01" * 49


def make_signer() -> ChallengeSigner:
    return ChallengeSigner.from_hex(VALID_HEX, 3)


def test_from_hex_happy_path():
    s = ChallengeSigner.from_hex(VALID_HEX, 3)
    assert len(s.header) == 49
    assert s.trailer == 3


def test_from_hex_rejects_non_hex():
    with pytest.raises(ValueError, match="invalid CHALLENGE_HEADER_HEX"):
        ChallengeSigner.from_hex("not hex", 3)


def test_from_hex_rejects_wrong_length():
    with pytest.raises(ValueError, match="49 bytes"):
        ChallengeSigner.from_hex("ab" * 10, 3)  # only 10 bytes


def test_from_hex_rejects_trailer_out_of_range():
    with pytest.raises(ValueError, match="0..255"):
        ChallengeSigner.from_hex(VALID_HEX, 256)
    with pytest.raises(ValueError, match="0..255"):
        ChallengeSigner.from_hex(VALID_HEX, -1)


def test_sign_returns_base64():
    s = make_signer()
    h = s.sign()
    # base64 of 70 bytes = 96 chars (with padding).
    assert len(h) == 96
    # Round-trip: must decode to 70 bytes.
    raw = base64.b64decode(h)
    assert len(raw) == 70
    # First 49 bytes are the static header (un-XORed).
    assert raw[:49] == bytes.fromhex(VALID_HEX)
    # Bytes 49..69 are the XOR-padded region - we don't check the
    # exact value because it depends on the random nonce + counter, but
    # we do verify the 21 bytes are NOT all zero (proves the nonce was
    # actually mixed in).
    assert any(b != 0 for b in raw[49:])


def test_sign_is_unique_per_call():
    """Two calls should never produce the same header (random nonce)."""
    s = make_signer()
    seen = {s.sign() for _ in range(50)}
    # 50 calls, all distinct - probability of collision is 2^-920, zero.
    assert len(seen) == 50


def test_sign_includes_only_printable_chars():
    s = make_signer()
    h = s.sign()
    allowed = set(string.ascii_letters + string.digits + "+/=")
    assert set(h).issubset(allowed)


def test_summary_contains_no_secrets():
    s = make_signer()
    summary = s.summary()
    assert "49" in summary
    assert "3" in summary
    # Make sure we don't leak the actual header bytes.
    assert VALID_HEX not in summary