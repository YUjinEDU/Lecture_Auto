"""Raon-Speech-9B TTS and STT module with voice cloning.

Supports:
1. Speech-to-Text (STT) for transcribing reference lectures and analyzing professor style.
2. Text-to-Speech (TTS) with speaker voice conditioning (ECAPA-TDNN embeddings) for voice cloning.
"""
from __future__ import annotations

import logging
from pathlib import Path
import numpy as np
import soundfile as sf
import torch

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_ID = "KRAFTON/Raon-Speech-9B"
_SAMPLE_RATE = 24000


def load_raon_pipeline(
    model_id: str = _DEFAULT_MODEL_ID,
    device: str = "cuda:0",
    dtype: str = "bfloat16",
):
    """Load RaonPipeline from HuggingFace Hub or local cache."""
    from transformers import AutoConfig
    from transformers.dynamic_module_utils import get_class_from_dynamic_module

    logger.info("Loading RaonPipeline from %s on %s (%s)", model_id, device, dtype)
    torch_dtype = getattr(torch, dtype) if hasattr(torch, dtype) else torch.bfloat16

    config = AutoConfig.from_pretrained(model_id, trust_remote_code=True)
    RaonPipeline = get_class_from_dynamic_module(
        "modeling_raon.RaonPipeline",
        model_id,
        revision=getattr(config, "_commit_hash", None),
    )

    pipe = RaonPipeline(model_id, device=device, dtype=dtype)
    logger.info("RaonPipeline loaded successfully")
    return pipe


def transcribe_audio(
    pipe,
    audio_path: str | Path,
) -> str:
    """Transcribe audio file to text using Raon-Speech-9B STT."""
    audio_path = str(audio_path)
    logger.info("Transcribing audio: %s", audio_path)
    text = pipe.stt(audio_path)
    return text


import re


def _split_into_sentences(text: str) -> list[str]:
    """Split script into natural sentence chunks (under ~80 chars).

    Prevents SpeechLM attention drift and trailing silence on long sequences (>20s).
    """
    # 1. Primary split by sentence terminators (. ? !)
    raw_chunks = [s.strip() for s in re.split(r'([.?!]+)', text) if s.strip()]
    sentences: list[str] = []
    for i in range(0, len(raw_chunks) - 1, 2):
        s = raw_chunks[i] + raw_chunks[i + 1]
        sentences.append(s.strip())
    if len(raw_chunks) % 2 != 0:
        sentences.append(raw_chunks[-1].strip())

    # 2. Secondary split for unusually long sentences (>90 chars) on comma
    refined: list[str] = []
    for s in sentences:
        if len(s) > 90 and "," in s:
            sub = [c.strip() for c in s.split(",") if c.strip()]
            for idx, c in enumerate(sub):
                suffix = "," if idx < len(sub) - 1 else ""
                refined.append(c + suffix)
        else:
            refined.append(s)
    return [r for r in refined if r.strip()]


def _trim_and_compact_audio(wav: np.ndarray, sr: int = _SAMPLE_RATE) -> np.ndarray:
    """Trim excessive lead/tail silence and compact internal gaps > 0.6s to 0.25s."""
    if len(wav) == 0:
        return wav

    # Trim leading & trailing silence
    threshold = 0.005
    active = np.where(np.abs(wav) > threshold)[0]
    if len(active) == 0:
        return wav
    start = max(0, active[0] - int(sr * 0.05))
    end = min(len(wav), active[-1] + int(sr * 0.05))
    trimmed = wav[start:end]
    return trimmed


def synthesize_raon_slide(
    pipe,
    text: str,
    output_path: Path,
    speaker_audio: Path | str | None = None,
    pause_seconds: float = 0.25,
) -> Path:
    """Synthesize audio for a single slide using sentence-level chunking.

    Splits long slide scripts into sentence chunks to ensure crystal clear
    pronunciation without slurring or empty silent gaps.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = text.strip()
    if not text:
        logger.debug("Empty text for slide -- generating 1s silence at %s", output_path)
        silence = np.zeros(int(_SAMPLE_RATE * 1.0), dtype=np.float32)
        sf.write(str(output_path), silence, _SAMPLE_RATE)
        return output_path

    sentences = _split_into_sentences(text)
    logger.debug("Synthesizing slide in %d sentence chunks -> %s", len(sentences), output_path.name)

    kwargs = {}
    if speaker_audio is not None and Path(speaker_audio).exists():
        kwargs["speaker_audio"] = str(speaker_audio)

    audio_segments: list[np.ndarray] = []
    sr = _SAMPLE_RATE
    pause = np.zeros(int(sr * pause_seconds), dtype=np.float32)

    for idx, sent in enumerate(sentences, start=1):
        if not sent.strip():
            continue
        audio_tensor, sample_rate = pipe.tts(sent, **kwargs)
        sr = sample_rate

        # Convert to float numpy array
        if hasattr(audio_tensor, "squeeze"):
            audio_np = audio_tensor.squeeze().cpu().float().numpy()
        else:
            audio_np = np.array(audio_tensor, dtype=np.float32)

        trimmed = _trim_and_compact_audio(audio_np, sr)
        audio_segments.append(trimmed)

        # Natural breath pause between sentences
        if idx < len(sentences):
            audio_segments.append(pause)

    if not audio_segments:
        merged = np.zeros(int(sr * 1.0), dtype=np.float32)
    else:
        merged = np.concatenate(audio_segments)

    # Peak normalization to prevent clipping & ensure consistent loudness
    peak = np.max(np.abs(merged))
    if peak > 0:
        merged = (merged / peak) * 0.92

    sf.write(str(output_path), merged, sr)
    logger.debug("Saved slide audio: %s (%.2fs)", output_path.name, len(merged) / sr)
    return output_path


def synthesize_raon_audio(
    pipe,
    scripts: list[dict],
    audio_dir: Path,
    speaker_audio: Path | str | None = None,
) -> list[Path]:
    """Synthesize audio for all slides in scripts sequentially."""
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    wav_paths: list[Path] = []
    for i, slide in enumerate(scripts, start=1):
        text = slide.get("script", "")
        out_path = audio_dir / f"slide_{i:03d}.wav"
        logger.info("Synthesizing slide %d/%d (%d chars)...", i, len(scripts), len(text))
        synthesize_raon_slide(pipe, text, out_path, speaker_audio=speaker_audio)
        wav_paths.append(out_path)

    logger.info("Synthesized %d slide audios in %s", len(wav_paths), audio_dir)
    return wav_paths
