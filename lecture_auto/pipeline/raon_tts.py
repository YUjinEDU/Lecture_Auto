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


def synthesize_raon_slide(
    pipe,
    text: str,
    output_path: Path,
    speaker_audio: Path | str | None = None,
) -> Path:
    """Synthesize audio for a single slide using Raon-Speech-9B."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = text.strip()
    if not text:
        logger.debug("Empty text for slide -- generating 1s silence at %s", output_path)
        silence = np.zeros(int(_SAMPLE_RATE * 1.0), dtype=np.float32)
        sf.write(str(output_path), silence, _SAMPLE_RATE)
        return output_path

    logger.debug("Synthesizing slide audio (%d chars) -> %s", len(text), output_path.name)
    kwargs = {}
    if speaker_audio is not None and Path(speaker_audio).exists():
        kwargs["speaker_audio"] = str(speaker_audio)

    audio, sr = pipe.tts(text, **kwargs)
    pipe.save_audio((audio, sr), str(output_path))
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
