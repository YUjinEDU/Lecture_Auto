"""Abstract TTS engine interface.

Consumers (Celery tasks, demo, CLI) depend only on :class:`TTSEngine`, so
swapping the underlying model is a config change (``TTS_ENGINE`` env var) rather
than a code change. See :func:`lecture_auto.tts.get_tts_engine`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSEngine(ABC):
    """A text-to-speech engine that renders one slide's script to a WAV file."""

    @abstractmethod
    def synthesize_slide(
        self,
        text: str,
        output_path: Path,
        *,
        voice_ref_path: Path | None = None,
        voice_ref_text: str | None = None,
    ) -> Path:
        """Synthesize ``text`` to a WAV at ``output_path``; return that path.

        Contract every engine must honor:
        - Empty / whitespace-only ``text`` produces a short silence clip, never
          an error (keeps per-slide pipelines resumable).
        - ``voice_ref_path`` enables voice cloning when the engine supports it;
          engines without cloning may ignore it and use a default voice.
        """
        raise NotImplementedError
