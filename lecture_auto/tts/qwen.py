"""Qwen3-TTS engine — local voice-clone synthesis.

Thin adapter over the low-level functions in :mod:`lecture_auto.pipeline.tts`
(which keep their own unit tests). The model loads lazily on first use so the
engine can be constructed cheaply (e.g. by the factory) without touching the GPU.
"""
from __future__ import annotations

import os
from pathlib import Path

from lecture_auto.tts.base import TTSEngine

# Default Qwen3-TTS model; override per-deployment with the TTS_MODEL env var.
DEFAULT_QWEN_TTS_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"


class QwenTTSEngine(TTSEngine):
    """Local Qwen3-TTS with voice cloning."""

    def __init__(self, model_path: str | None = None) -> None:
        self._model_path = model_path or os.environ.get(
            "TTS_MODEL", DEFAULT_QWEN_TTS_MODEL
        )
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from lecture_auto.pipeline.tts import load_tts

            self._model = load_tts(self._model_path)
        return self._model

    def synthesize_slide(
        self,
        text: str,
        output_path: Path,
        *,
        voice_ref_path: Path | None = None,
        voice_ref_text: str | None = None,
    ) -> Path:
        from lecture_auto.pipeline.tts import synthesize_slide as _synthesize_slide

        return _synthesize_slide(
            self._ensure_model(),
            text,
            output_path,
            voice_ref_path=voice_ref_path,
            voice_ref_text=voice_ref_text,
        )
