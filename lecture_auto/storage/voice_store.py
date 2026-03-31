"""Voice reference file storage (per-professor).

Manages voice reference audio files used for TTS voice cloning.
Each professor gets a directory under ``VOICE_REF_ROOT`` containing
their ``voice_ref.wav`` file.

For MVP (no auth yet per deferred INFRA-03), use ``professor_id="default"``.

Exports:
    save_voice_ref     -- Save uploaded voice reference bytes to disk
    get_voice_ref      -- Retrieve voice reference path (or None)
    convert_webm_to_wav -- Convert browser-recorded WebM to WAV via ffmpeg
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

VOICE_REF_ROOT = Path(os.environ.get("VOICE_REF_ROOT", "/data/voices"))


def save_voice_ref(professor_id: str, audio_bytes: bytes) -> Path:
    """Save voice reference audio bytes to disk.

    Parameters
    ----------
    professor_id:
        Unique identifier for the professor. Use ``"default"`` for MVP.
    audio_bytes:
        Raw WAV audio bytes to save.

    Returns
    -------
    Path
        Absolute path to the saved ``voice_ref.wav`` file.
    """
    ref_dir = VOICE_REF_ROOT / professor_id
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_path = ref_dir / "voice_ref.wav"
    ref_path.write_bytes(audio_bytes)
    logger.info("Saved voice reference for %s at %s (%d bytes)",
                professor_id, ref_path, len(audio_bytes))
    return ref_path


def get_voice_ref(professor_id: str) -> Path | None:
    """Retrieve the voice reference path for a professor.

    Parameters
    ----------
    professor_id:
        Unique identifier for the professor.

    Returns
    -------
    Path | None
        Path to ``voice_ref.wav`` if it exists, otherwise ``None``.
    """
    ref_path = VOICE_REF_ROOT / professor_id / "voice_ref.wav"
    if ref_path.exists():
        return ref_path
    return None


def convert_webm_to_wav(webm_bytes: bytes) -> bytes:
    """Convert WebM audio (from browser recording) to WAV via ffmpeg.

    Produces 16-bit PCM, mono, 24000 Hz WAV output suitable for
    Qwen3-TTS voice cloning.

    Parameters
    ----------
    webm_bytes:
        Raw WebM audio bytes from the browser MediaRecorder API.

    Returns
    -------
    bytes
        WAV audio bytes (PCM s16le, 24000 Hz, mono).

    Raises
    ------
    RuntimeError
        If ffmpeg conversion fails.
    """
    result = subprocess.run(
        [
            "ffmpeg",
            "-i", "pipe:0",
            "-f", "wav",
            "-acodec", "pcm_s16le",
            "-ar", "24000",
            "-ac", "1",
            "pipe:1",
        ],
        input=webm_bytes,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg WebM-to-WAV conversion failed (exit {result.returncode}): "
            f"{result.stderr.decode(errors='replace')}"
        )
    logger.debug("Converted WebM to WAV: %d -> %d bytes",
                 len(webm_bytes), len(result.stdout))
    return result.stdout
