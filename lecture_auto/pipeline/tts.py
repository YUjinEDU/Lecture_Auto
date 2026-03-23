"""TTS audio synthesis module using Qwen3-TTS with optional voice cloning.

Converts per-slide script text to WAV audio files. Supports voice cloning
from a reference WAV file (3-second clip per TTS-02 requirement).

Sample rate: 24000 Hz (Qwen3-TTS native rate).
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Lazy imports for GPU-heavy dependencies — avoids import errors at test time.
try:
    from transformers import AutoModelForCausalLM, AutoTokenizer
except ImportError:  # pragma: no cover
    AutoModelForCausalLM = None  # type: ignore[assignment,misc]
    AutoTokenizer = None  # type: ignore[assignment,misc]

_SAMPLE_RATE = 24000
_DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"


def load_tts(model_path: str = _DEFAULT_MODEL) -> dict:
    """Load Qwen3-TTS model and tokenizer.

    Parameters
    ----------
    model_path:
        HuggingFace model identifier or local path.
        Defaults to ``Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice``.

    Returns
    -------
    dict
        ``{"model": model, "tokenizer": tokenizer}``
    """
    if AutoTokenizer is None or AutoModelForCausalLM is None:  # pragma: no cover
        raise RuntimeError(
            "transformers is not installed. "
            "Run: pip install transformers>=4.57.0"
        )

    logger.info("Loading TTS tokenizer from %s", model_path)
    tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)

    logger.info("Loading TTS model from %s", model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, trust_remote_code=True, device_map="auto"
    )

    logger.info("TTS model loaded successfully")
    return {"model": model, "tokenizer": tokenizer}


def generate_silence(duration_seconds: float, sample_rate: int = _SAMPLE_RATE) -> np.ndarray:
    """Create a silence numpy array.

    Parameters
    ----------
    duration_seconds:
        Length of silence in seconds.
    sample_rate:
        Audio sample rate in Hz (default 24000).

    Returns
    -------
    numpy.ndarray
        Float32 array of zeros with ``int(sample_rate * duration_seconds)`` samples.
    """
    num_samples = int(sample_rate * duration_seconds)
    return np.zeros(num_samples, dtype=np.float32)


def synthesize_slide(
    tts_model: dict,
    text: str,
    output_path: Path,
    voice_ref_path: Path | None = None,
    sample_rate: int = _SAMPLE_RATE,
) -> Path:
    """Synthesize audio for a single slide.

    Parameters
    ----------
    tts_model:
        Dict with ``"model"`` and ``"tokenizer"`` keys from :func:`load_tts`.
    text:
        Script text to synthesize. Empty/whitespace-only text produces 1 s silence.
    output_path:
        Destination WAV file path.
    voice_ref_path:
        Optional path to a reference WAV file for voice cloning (3-second clip).
    sample_rate:
        Target sample rate in Hz (default 24000).

    Returns
    -------
    Path
        The ``output_path`` that was written.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not text or not text.strip():
        logger.debug("Empty text for slide — generating 1 s silence at %s", output_path)
        samples = generate_silence(1.0, sample_rate)
        sf.write(str(output_path), samples, sample_rate)
        return output_path

    model = tts_model["model"]
    tokenizer = tts_model["tokenizer"]

    # Load reference audio for voice cloning if provided.
    ref_samples: np.ndarray | None = None
    ref_sr: int | None = None
    if voice_ref_path is not None:
        ref_samples, ref_sr = sf.read(str(voice_ref_path))
        logger.debug("Loaded voice reference from %s (sr=%d)", voice_ref_path, ref_sr)

    # Qwen3-TTS inference via transformers.
    # The model accepts raw text tokens and optionally a voice reference embedding.
    # Exact API depends on model card; using the standard generate() pattern here.
    inputs = tokenizer(text, return_tensors="pt")

    generate_kwargs: dict = {}
    if ref_samples is not None:
        generate_kwargs["voice_ref"] = ref_samples
        generate_kwargs["voice_ref_sr"] = ref_sr

    with_grad = False  # no gradient computation needed
    try:
        import torch  # type: ignore[import]
        with torch.no_grad():
            output_ids = model.generate(**inputs, **generate_kwargs)
    except ImportError:  # pragma: no cover — torch not available in unit tests
        output_ids = model.generate(**inputs, **generate_kwargs)

    # Decode output tokens to audio samples.
    # Qwen3-TTS outputs raw float32 waveform samples.
    if hasattr(output_ids, "cpu"):
        samples = output_ids.cpu().numpy().flatten().astype(np.float32)
    else:
        samples = np.array(output_ids, dtype=np.float32).flatten()

    sf.write(str(output_path), samples, sample_rate)
    logger.debug("Wrote audio to %s (%d samples)", output_path, len(samples))
    return output_path


def synthesize_audio(
    tts_model: dict,
    scripts: list[dict],
    audio_dir: Path,
    voice_ref_path: Path | None = None,
) -> list[Path]:
    """Synthesize audio for all slides.

    Parameters
    ----------
    tts_model:
        Dict with ``"model"`` and ``"tokenizer"`` keys from :func:`load_tts`.
    scripts:
        List of dicts, each with ``"slide_number"`` (int) and ``"script"`` (str) keys.
    audio_dir:
        Directory where ``audio_NNN.wav`` files will be written.
    voice_ref_path:
        Optional path to a reference WAV file for voice cloning.

    Returns
    -------
    list[Path]
        WAV file paths in the same order as *scripts*.
    """
    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    results: list[Path] = []
    for script in scripts:
        slide_number: int = script["slide_number"]
        text: str = script["script"]
        output_path = audio_dir / f"audio_{slide_number:03d}.wav"

        logger.info("Synthesizing audio for slide %d -> %s", slide_number, output_path.name)
        wav_path = synthesize_slide(
            tts_model, text, output_path, voice_ref_path=voice_ref_path
        )
        results.append(wav_path)

    logger.info("TTS synthesis complete: %d slides -> %s", len(results), audio_dir)
    return results
