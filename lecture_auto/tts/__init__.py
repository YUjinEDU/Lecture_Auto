"""Pluggable TTS engines.

Select the active engine with the ``TTS_ENGINE`` env var (default ``"qwen"``)::

    from lecture_auto.tts import get_tts_engine
    engine = get_tts_engine()                      # honors TTS_ENGINE
    engine.synthesize_slide(text, out_path, voice_ref_path=ref)

Add a new engine by implementing :class:`TTSEngine` and registering it — no
consumer code changes::

    from lecture_auto.tts import register
    register("fish", FishTTSEngine)
"""
from __future__ import annotations

import os
from typing import Callable

from lecture_auto.tts.base import TTSEngine
from lecture_auto.tts.qwen import QwenTTSEngine

# name -> zero-arg factory returning a TTSEngine
_REGISTRY: dict[str, Callable[[], TTSEngine]] = {
    "qwen": QwenTTSEngine,
}


def register(name: str, factory: Callable[[], TTSEngine]) -> None:
    """Register a TTSEngine factory under ``name`` (case-insensitive)."""
    _REGISTRY[name.lower()] = factory


def available_engines() -> list[str]:
    """Return the sorted list of registered engine names."""
    return sorted(_REGISTRY)


def get_tts_engine(name: str | None = None) -> TTSEngine:
    """Return a TTSEngine for ``name`` (falls back to the ``TTS_ENGINE`` env var).

    Raises:
        ValueError: if ``name`` is not a registered engine.
    """
    name = (name or os.environ.get("TTS_ENGINE", "qwen")).lower()
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown TTS engine {name!r}. Available: {available_engines()}"
        )
    return factory()


__all__ = [
    "TTSEngine",
    "QwenTTSEngine",
    "get_tts_engine",
    "register",
    "available_engines",
]
