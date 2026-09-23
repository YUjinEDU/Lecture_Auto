"""TTS audio synthesis module using qwen-tts (Qwen3-TTS Base) with voice cloning.

Converts per-slide script text to WAV audio files. Supports voice cloning
from a reference WAV file (3-second clip per TTS-02 requirement).

Uses the ``qwen-tts`` package with ``Qwen3TTSModel`` for inference instead of
raw transformers, providing voice-clone and custom-voice generation APIs.

Sample rate: 24000 Hz (Qwen3-TTS native rate).
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# Lazy imports for GPU-heavy dependencies -- avoids import errors at test time.
try:
    from qwen_tts import Qwen3TTSModel
except ImportError:  # pragma: no cover
    Qwen3TTSModel = None  # type: ignore[assignment,misc]

_SAMPLE_RATE = 24000
# Default Qwen3-TTS model; override per-deployment with the TTS_MODEL env var.
_DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"


def load_tts(model_path: str = _DEFAULT_MODEL) -> "Qwen3TTSModel":
    """Load Qwen3-TTS Base model via qwen-tts package.

    Parameters
    ----------
    model_path:
        HuggingFace model identifier or local path.
        Defaults to ``Qwen/Qwen3-TTS-12Hz-1.7B-Base``.

    Returns
    -------
    Qwen3TTSModel
        Ready-to-use TTS model instance.
    """
    if Qwen3TTSModel is None:  # pragma: no cover
        raise RuntimeError(
            "qwen-tts is not installed. "
            "Run: pip install qwen-tts"
        )

    try:
        import torch  # type: ignore[import]
    except ImportError:  # pragma: no cover
        torch = None  # type: ignore[assignment]

    logger.info("Loading TTS model from %s", model_path)
    kwargs: dict = {"device_map": "cuda:0"}
    if torch is not None:
        kwargs["dtype"] = torch.bfloat16
    model = Qwen3TTSModel.from_pretrained(model_path, **kwargs)
    logger.info("TTS model loaded successfully")
    return model


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
    model: "Qwen3TTSModel",
    text: str,
    output_path: Path,
    voice_ref_path: Path | None = None,
    voice_ref_text: str | None = None,
    sample_rate: int = _SAMPLE_RATE,
) -> Path:
    """Synthesize audio for a single slide.

    Parameters
    ----------
    model:
        ``Qwen3TTSModel`` instance from :func:`load_tts`.
    text:
        Script text to synthesize. Empty/whitespace-only text produces 1 s silence.
    output_path:
        Destination WAV file path.
    voice_ref_path:
        Optional path to a reference WAV file for voice cloning (3-second clip).
    voice_ref_text:
        Optional transcript of the reference audio. When ``None`` and
        ``voice_ref_path`` is provided, x-vector-only mode is used.
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
        logger.debug("Empty text for slide -- generating 1 s silence at %s", output_path)
        samples = generate_silence(1.0, sample_rate)
        sf.write(str(output_path), samples, sample_rate)
        return output_path

    # Voice-cloned generation when a reference is available.
    if voice_ref_path is not None:
        logger.debug("Voice-clone synthesis with ref=%s", voice_ref_path)
        wavs, sr = model.generate_voice_clone(
            text=text,
            ref_audio=str(voice_ref_path),
            ref_text=voice_ref_text or "",
            x_vector_only_mode=(voice_ref_text is None),
        )
    else:
        # Fallback: default speaker without voice cloning.
        logger.debug("Default-speaker synthesis (no voice ref)")
        wavs, sr = model.generate_custom_voice(
            text=text,
            speaker="Chelsie",
            language="ko",
        )

    # wavs is a list of waveform arrays; take the first.
    samples = np.array(wavs[0], dtype=np.float32).flatten()
    sf.write(str(output_path), samples, sr or sample_rate)
    logger.debug("Wrote audio to %s (%d samples)", output_path, len(samples))
    return output_path


def synthesize_audio(
    model: "Qwen3TTSModel",
    scripts: list[dict],
    audio_dir: Path,
    voice_ref_path: Path | None = None,
) -> list[Path]:
    """Synthesize audio for all slides.

    Parameters
    ----------
    model:
        ``Qwen3TTSModel`` instance from :func:`load_tts`.
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
            model, text, output_path, voice_ref_path=voice_ref_path
        )
        results.append(wav_path)

    logger.info("TTS synthesis complete: %d slides -> %s", len(results), audio_dir)
    return results


def merge_audio(
    audio_source: Path | Sequence[Path],
    output_path: Path,
    sample_rate: int = _SAMPLE_RATE,
) -> Path:
    """Merge per-slide WAV files into a single concatenated WAV.

    Parameters
    ----------
    audio_source:
        Either a directory containing ``audio_NNN.wav``/``slide_NNN.wav``
        files (existing glob-based behavior -- all matching files in sorted
        order), or an explicit, already-ordered list/tuple of WAV paths to
        concatenate verbatim, with no globbing. The list form exists so a
        caller (e.g. ``assemble_video``) can merge exactly the slides it
        resolved, ignoring any unrelated ``*.wav`` file that happens to sit
        in the same directory.
    output_path:
        Destination path for the merged WAV file.
    sample_rate:
        Sample rate for the output file (default 24000).

    Returns
    -------
    Path
        The ``output_path`` that was written.

    Raises
    ------
    FileNotFoundError
        If no WAV files are found (directory form) or the list is empty.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(audio_source, (list, tuple)):
        sorted_files = [Path(f) for f in audio_source]
    else:
        audio_dir = Path(audio_source)
        sorted_files = sorted(audio_dir.glob("slide_*.wav")) or sorted(audio_dir.glob("audio_*.wav")) or sorted(audio_dir.glob("*.wav"))
        # Exclude the merged file itself if it already exists in the directory.
        sorted_files = [f for f in sorted_files if f.name != output_path.name]

    if not sorted_files:
        raise FileNotFoundError(f"No WAV files found for merge (source={audio_source!r})")

    segments = [sf.read(str(f))[0] for f in sorted_files]
    merged = np.concatenate(segments)
    sf.write(str(output_path), merged, sample_rate)

    logger.info("Merged %d audio files -> %s", len(sorted_files), output_path)
    return output_path
