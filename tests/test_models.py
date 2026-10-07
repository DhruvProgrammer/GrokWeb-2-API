"""Tests for the OpenAI wire-format models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from grok_web_to_api.models import (
    ChatRequest,
    default_model_list,
    is_valid_model,
    map_model,
    new_chunk_id,
)


def test_map_model_known_values():
    cases = {
        "grok-auto": "auto",
        "auto": "auto",
        "grok-4": "grok-4",
        "grok-4-fast": "grok-4-fast",
        "grok-3": "grok-3",
        "grok-3-mini": "grok-3-mini",
        "grok-2": "grok-2",
        "grok-2-mini": "grok-2-mini",
    }
    for in_, want in cases.items():
        assert map_model(in_) == want


def test_map_model_unknown_falls_back_to_auto():
    assert map_model("gpt-4-turbo") == "auto"
    assert map_model("claude-3-opus") == "auto"
    assert map_model("") == "auto"


def test_is_valid_model():
    valid = ["grok-auto", "auto", "grok-4", "grok-4-fast", "grok-3", "grok-3-mini", "grok-2", "grok-2-mini"]
    for m in valid:
        assert is_valid_model(m), f"{m} should be valid"

    for m in ["", "gpt-4", "claude-3", "random-model"]:
        assert not is_valid_model(m), f"{m} should be invalid"


def test_default_model_list_shape():
    models = default_model_list()
    assert len(models) >= 5
    ids = {m.id for m in models}
    assert "grok-auto" in ids
    assert "grok-4" in ids
    assert "grok-3" in ids
    # All entries must have correct object type and a created timestamp.
    for m in models:
        assert m.object == "model"
        assert m.owned_by == "xai"
        assert isinstance(m.created, int)
        assert m.created > 1_700_000_000  # sanity: post-2023


def test_chat_request_minimal():
    req = ChatRequest(model="grok-auto", messages=[{"role": "user", "content": "hi"}])
    assert req.stream is False
    assert req.temperature is None
    assert req.max_tokens is None


def test_chat_request_rejects_missing_model():
    with pytest.raises(ValidationError):
        ChatRequest(messages=[{"role": "user", "content": "hi"}])


def test_chat_request_rejects_missing_messages():
    with pytest.raises(ValidationError):
        ChatRequest(model="grok-auto")


def test_chat_request_ignores_unknown_fields():
    # Pydantic is configured to ignore extras - the request must not
    # 400 when clients send temperature, tools, etc.
    req = ChatRequest(
        model="grok-auto",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.5,
        top_p=0.9,
    )
    assert req.temperature == 0.5
    assert req.top_p == 0.9


def test_new_chunk_id_format():
    cid = new_chunk_id()
    assert cid.startswith("chatcmpl-")
    # Should be long enough to be unique.
    assert len(cid) >= 30