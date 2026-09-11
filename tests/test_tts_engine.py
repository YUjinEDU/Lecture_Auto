"""Tests for the pluggable TTS engine factory (lecture_auto.tts).

Verifies that swapping the engine is a config/registry change — the core
requirement behind the TTSEngine abstraction.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import lecture_auto.pipeline.tts as tts_module
from lecture_auto.tts import (
    TTSEngine,
    available_engines,
    get_tts_engine,
    register,
)
from lecture_auto.tts.qwen import QwenTTSEngine


def test_default_engine_is_qwen(monkeypatch):
    monkeypatch.delenv("TTS_ENGINE", raising=False)
    assert isinstance(get_tts_engine(), QwenTTSEngine)


def test_env_var_selects_engine(monkeypatch):
    monkeypatch.setenv("TTS_ENGINE", "qwen")
    assert isinstance(get_tts_engine(), QwenTTSEngine)


def test_unknown_engine_raises(monkeypatch):
    monkeypatch.setenv("TTS_ENGINE", "does-not-exist")
    with pytest.raises(ValueError):
        get_tts_engine()


def test_register_and_swap_engine(monkeypatch):
    """A newly registered engine becomes selectable via TTS_ENGINE — no consumer change."""

    class DummyEngine(TTSEngine):
        def synthesize_slide(
            self, text, output_path, *, voice_ref_path=None, voice_ref_text=None
        ):
            return output_path

    register("dummy", DummyEngine)
    assert "dummy" in available_engines()

    monkeypatch.setenv("TTS_ENGINE", "dummy")
    assert isinstance(get_tts_engine(), DummyEngine)


def test_qwen_engine_delegates_to_pipeline(tmp_path):
    """QwenTTSEngine forwards to pipeline.tts with the lazily loaded model."""
    fake_model = MagicMock()
    out = tmp_path / "audio_001.wav"

    with patch.object(tts_module, "load_tts", return_value=fake_model) as mock_load, \
         patch.object(tts_module, "synthesize_slide", return_value=out) as mock_synth:
        engine = QwenTTSEngine(model_path="x/y")
        result = engine.synthesize_slide("안녕하세요", out, voice_ref_path=None)

    assert result == out
    mock_load.assert_called_once_with("x/y")
    args, kwargs = mock_synth.call_args
    assert args[0] is fake_model       # loaded model forwarded first
    assert args[1] == "안녕하세요"       # then the text
