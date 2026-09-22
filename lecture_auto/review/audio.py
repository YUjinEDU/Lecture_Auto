"""Audio utilities for slicing raw lecture audio and synthesizing AI review audio."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def slice_raw_audio(
    input_audio_path: str | Path,
    start_sec: float,
    end_sec: float,
    output_audio_path: str | Path,
) -> Path:
    """Extract a precise slice from raw class recording using ffmpeg."""
    in_p = Path(input_audio_path)
    out_p = Path(output_audio_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_sec),
        "-to",
        str(end_sec),
        "-i",
        str(in_p),
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(out_p),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        logger.error("ffmpeg audio slice failed: %s", result.stderr)
        raise RuntimeError(f"ffmpeg failed with exit code {result.returncode}: {result.stderr[:200]}")

    logger.info("Successfully sliced raw audio to %s (%.1fs - %.1fs)", out_p, start_sec, end_sec)
    return out_p


def synthesize_review_speech(
    script_text: str,
    output_wav_path: str | Path,
    *,
    speaker_audio: str | Path = "data/audio_ref/reference_v1.wav",
    device: str = "cuda:1",
) -> tuple[Path, bool]:
    """Synthesize AI review audio using Raon-Speech-9B and professor voice reference."""
    from lecture_auto.pipeline.raon_tts import load_raon_pipeline, synthesize_raon_slide

    out_p = Path(output_wav_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    ref_p = Path(speaker_audio)

    pipe = load_raon_pipeline(device=device)
    out_path, ok = synthesize_raon_slide(
        pipe,
        script_text,
        out_p,
        speaker_audio=ref_p,
    )
    return out_path, ok
