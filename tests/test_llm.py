"""Tests for the unified LLM client (lecture_auto.llm).

The OpenAI SDK is mocked — no network / API key required. Replaces the coverage
that previously lived in the vLLM (load_vlm) and claude-subprocess (call_claude)
code paths.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lecture_auto.llm import (
    LLMClient,
    available_providers,
    get_llm_client,
    register,
)
from lecture_auto.llm.openai_client import (
    DEFAULT_TEXT_MODEL,
    DEFAULT_VLM_MODEL,
    OpenAILLMClient,
)


def _fake_openai(content: str = "hi") -> MagicMock:
    """A fake openai.OpenAI whose chat.completions.create returns ``content``."""
    fake = MagicMock()
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    fake.chat.completions.create.return_value = response
    return fake


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_default_provider_is_openai(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert isinstance(get_llm_client(), OpenAILLMClient)


def test_unknown_provider_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError):
        get_llm_client()


def test_register_and_swap_provider(monkeypatch):
    class DummyClient(LLMClient):
        def chat(self, messages, *, model=None, temperature=0.3, max_tokens=None):
            return "x"

        def complete_text(self, prompt, *, temperature=0.3, max_tokens=None):
            return "x"

        def analyze_image(self, image_path, prompt, *, temperature=0.1, max_tokens=1024):
            return "x"

    register("dummy", DummyClient)
    assert "dummy" in available_providers()
    monkeypatch.setenv("LLM_PROVIDER", "dummy")
    assert isinstance(get_llm_client(), DummyClient)


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

def test_default_models(monkeypatch):
    monkeypatch.delenv("LLM_SCRIPT_MODEL", raising=False)
    monkeypatch.delenv("LLM_VLM_MODEL", raising=False)
    client = OpenAILLMClient(api_key="k")
    assert client.text_model == DEFAULT_TEXT_MODEL
    assert client.vlm_model == DEFAULT_VLM_MODEL


def test_env_overrides_models(monkeypatch):
    monkeypatch.setenv("LLM_SCRIPT_MODEL", "custom-text")
    monkeypatch.setenv("LLM_VLM_MODEL", "custom-vlm")
    client = OpenAILLMClient(api_key="k")
    assert client.text_model == "custom-text"
    assert client.vlm_model == "custom-vlm"


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------

def test_complete_text_sends_user_message():
    fake = _fake_openai("script text")
    with patch("openai.OpenAI", return_value=fake):
        client = OpenAILLMClient(api_key="k", text_model="m")
        out = client.complete_text("hello prompt")

    assert out == "script text"
    _, kwargs = fake.chat.completions.create.call_args
    assert kwargs["model"] == "m"
    assert kwargs["messages"] == [{"role": "user", "content": "hello prompt"}]


def test_analyze_image_builds_image_message(tmp_path: Path):
    png = tmp_path / "slide.png"
    png.write_bytes(b"\x89PNG fake bytes")

    fake = _fake_openai('{"visual_summary": "ok"}')
    with patch("openai.OpenAI", return_value=fake):
        client = OpenAILLMClient(api_key="k", vlm_model="vm")
        out = client.analyze_image(png, "analyze this", max_tokens=500)

    assert out == '{"visual_summary": "ok"}'
    _, kwargs = fake.chat.completions.create.call_args
    assert kwargs["model"] == "vm"
    assert kwargs["max_tokens"] == 500
    content = kwargs["messages"][0]["content"]
    kinds = {part["type"] for part in content}
    assert kinds == {"image_url", "text"}
    image_part = next(p for p in content if p["type"] == "image_url")
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = OpenAILLMClient(api_key=None)
    with pytest.raises(RuntimeError):
        client.complete_text("p")
