"""Raon-Speech-9B TTS and STT module with voice cloning.

Supports:
1. Speech-to-Text (STT) for transcribing reference lectures and analyzing professor style.
2. Text-to-Speech (TTS) with speaker voice conditioning (ECAPA-TDNN embeddings) for voice cloning.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
import numpy as np
import pyloudnorm as pyln
import soundfile as sf
import torch

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_ID = "KRAFTON/Raon-Speech-9B"
_SAMPLE_RATE = 24000

# Public: callers (batch_generate_lectures.py) need these to build a cache
# key that actually captures what changes the generated audio.
TTS_MODEL_ID = _DEFAULT_MODEL_ID
TTS_TEMPERATURE = 0.85


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

    # transformers prints a UserWarning at load time suggesting flash-attn for
    # audio >~20s (sdpa "ignores sliding_window"). DO NOT act on that warning
    # for this model: measured directly (same text, same task_params, only the
    # backend changed) -- attn_implementation="fa" makes RaonPipeline.tts() stop
    # generating almost immediately (0.7s output instead of ~29s on sdpa). This
    # is a real incompatibility in this model's custom generation code with FA2,
    # not a config issue on our side. Stay on sdpa until KRAFTON fixes it upstream.
    pipe = RaonPipeline(model_id, device=device, dtype=dtype, attn_implementation="sdpa")

    # Tune the "tts" task defaults (model author's own defaults, verified against
    # modeling_raon.py: max_new_tokens=512/~41s cap, temperature=1.2, ras_enabled
    # already True). We lower temperature per voice_clone_parameters.md.
    # max_new_tokens is intentionally NOT raised to a big flat number here:
    # generation uses do_sample=True with no fixed seed, and it does not always
    # stop cleanly -- a flat 1024 cap let one slide ramble into ~76s of quiet
    # babble after ~5s of real speech instead of stopping at its ~30s target.
    # synthesize_raon_slide() sets a per-call cap sized to that slide's own
    # target duration instead, so a bad sample is bounded, not left to run wild.
    pipe.task_params["tts"].update({
        "temperature": TTS_TEMPERATURE,
        "ras_enabled": True,
        "ras_window_size": 50,
        "ras_repetition_threshold": 0.5,
    })
    logger.info("RaonPipeline loaded successfully (tts task_params tuned: %s)", pipe.task_params["tts"])
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


def _trim_lead_tail_silence(wav: np.ndarray, sr: int = _SAMPLE_RATE) -> np.ndarray:
    """Trim excessive lead/tail silence, keeping a small natural pad."""
    if len(wav) == 0:
        return wav

    threshold = 0.005
    active = np.where(np.abs(wav) > threshold)[0]
    if len(active) == 0:
        return wav
    start = max(0, active[0] - int(sr * 0.05))
    end = min(len(wav), active[-1] + int(sr * 0.05))
    return wav[start:end]


_CODEC_FRAME_RATE = 12.5  # Mimi codec, verified in modeling_raon.py
_MIN_MAX_NEW_TOKENS = 300  # ~24s floor, room for a short slide + margin
_MAX_MAX_NEW_TOKENS = 1536  # ~123s ceiling; see ponytail note below

# A single pipe.tts() call over a whole 250+ char slide script is what was
# collapsing into long silent runs / runaway babble (measured: up to 82%
# internal silence, 122s output for a ~35s target). Splitting into short
# 1-2 sentence segments, gating each one, and retrying with a different seed
# on failure keeps every clip short enough for the model to actually finish
# its sentence and stop.
_SEGMENT_MIN_CHARS = 60
_SEGMENT_MAX_CHARS = 120
_CHARS_PER_SECOND = 7.0  # Korean speech rate, per professor_style_guide.md (~420 chars/min)
_PAUSE_MS = 200
TTS_SEEDS = (17, 29, 43)
_TARGET_LUFS = -20.0

# Quality gate thresholds (see docs/260911_강의영상제작/plan.md discussion).
_MIN_VOICED_RATIO = 0.65
_MAX_DURATION_RATIO = 1.8
_MAX_INTERNAL_SILENCE_S = 2.0
_LUFS_RANGE = (-26.0, -16.0)

_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+")


def _to_numpy(audio_tensor, sr_fallback: int = _SAMPLE_RATE) -> np.ndarray:
    if hasattr(audio_tensor, "squeeze"):
        return audio_tensor.squeeze().cpu().float().numpy()
    return np.array(audio_tensor, dtype=np.float32)


def split_into_segments(
    script: str,
    min_chars: int = _SEGMENT_MIN_CHARS,
    max_chars: int = _SEGMENT_MAX_CHARS,
) -> list[str]:
    """Group a script's sentences into ~60-120 char TTS-safe segments.

    Never splits mid-sentence -- a single sentence longer than max_chars is
    kept whole rather than cut, since a mid-sentence break sounds worse than
    a slightly long segment.
    """
    sentences = [s.strip() for s in _SENTENCE_END_RE.split(script.strip()) if s.strip()]
    segments: list[str] = []
    current = ""
    for sent in sentences:
        if not current:
            current = sent
            continue
        candidate = f"{current} {sent}"
        if len(current) < min_chars or len(candidate) <= max_chars:
            current = candidate
        else:
            segments.append(current)
            current = sent
    if current:
        segments.append(current)
    return segments


def _voiced_ratio(wav: np.ndarray, sr: int, frame_ms: float = 20, threshold: float = 0.02) -> float:
    frame_len = int(sr * frame_ms / 1000)
    if frame_len <= 0 or len(wav) < frame_len:
        return 0.0
    n_frames = len(wav) // frame_len
    frames = wav[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    return float(np.mean(rms > threshold))


def _longest_silence_seconds(wav: np.ndarray, sr: int, frame_ms: float = 20, threshold: float = 0.02) -> float:
    frame_len = int(sr * frame_ms / 1000)
    if frame_len <= 0 or len(wav) < frame_len:
        return 0.0
    n_frames = len(wav) // frame_len
    frames = wav[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    silent = rms <= threshold

    longest = run = 0
    for is_silent in silent:
        run = run + 1 if is_silent else 0
        longest = max(longest, run)
    return longest * frame_ms / 1000.0


def _integrated_lufs(wav: np.ndarray, sr: int) -> float:
    if len(wav) < sr * 0.4:  # BS.1770 needs at least one 400ms gating block
        return float("-inf")
    meter = pyln.Meter(sr)
    return meter.integrated_loudness(wav.astype(np.float64))


def _passes_quality_gate(wav: np.ndarray, sr: int, expected_seconds: float) -> bool:
    if len(wav) == 0:
        return False
    duration = len(wav) / sr
    if duration > expected_seconds * _MAX_DURATION_RATIO:
        return False
    if _voiced_ratio(wav, sr) < _MIN_VOICED_RATIO:
        return False
    if _longest_silence_seconds(wav, sr) > _MAX_INTERNAL_SILENCE_S:
        return False
    lufs = _integrated_lufs(wav, sr)
    return _LUFS_RANGE[0] <= lufs <= _LUFS_RANGE[1]


def _loudness_normalize(wav: np.ndarray, sr: int, target_lufs: float = _TARGET_LUFS) -> np.ndarray:
    loudness = _integrated_lufs(wav, sr)
    if not np.isfinite(loudness):
        return wav.astype(np.float32)
    normalized = pyln.normalize.loudness(wav.astype(np.float64), loudness, target_lufs)
    peak = np.max(np.abs(normalized))
    if peak > 1.0:
        normalized = normalized / peak * 0.98
    return normalized.astype(np.float32)


def _synthesize_segment_with_gate(
    pipe,
    text: str,
    speaker_audio: Path | str | None,
    expected_seconds: float,
) -> tuple[np.ndarray, int, bool]:
    """Synthesize one short segment, retrying with a different seed on gate failure."""
    kwargs = {}
    if speaker_audio is not None and Path(speaker_audio).exists():
        kwargs["speaker_audio"] = str(speaker_audio)

    max_new_tokens = int(
        min(max(expected_seconds * _CODEC_FRAME_RATE * 1.4, _MIN_MAX_NEW_TOKENS), _MAX_MAX_NEW_TOKENS)
    )
    pipe.task_params["tts"]["max_new_tokens"] = max_new_tokens

    fallback: tuple[np.ndarray, int] | None = None
    for seed in TTS_SEEDS:
        torch.manual_seed(seed)
        audio_tensor, sr = pipe.tts(text, **kwargs)
        trimmed = _trim_lead_tail_silence(_to_numpy(audio_tensor, sr), sr)
        if _passes_quality_gate(trimmed, sr, expected_seconds):
            return trimmed, sr, True
        if fallback is None:
            fallback = (trimmed, sr)

    logger.warning("Segment failed quality gate after seeds %s: %r", TTS_SEEDS, text[:60])
    return fallback[0], fallback[1], False


def synthesize_raon_slide(
    pipe,
    text: str,
    output_path: Path,
    speaker_audio: Path | str | None = None,
    max_seconds: float | None = None,
) -> Path:
    """Synthesize a slide's script as short, quality-gated segments.

    A single pipe.tts() call over a whole slide script (250+ chars) is what
    caused audio collapse: long internal silences and 2-4x runaway duration,
    because generation isn't reliable at that length. Instead each ~1-2
    sentence segment (see split_into_segments) is synthesized and gate-checked
    independently, retried on a different seed if it fails, then joined with a
    short pause and loudness-normalized once as a whole.

    ``max_seconds`` is currently unused for the overall cap (each segment
    sizes its own generation budget from its char count) but is still
    accepted for call-site compatibility.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = text.strip()
    if not text:
        logger.debug("Empty text for slide -- generating 1s silence at %s", output_path)
        silence = np.zeros(int(_SAMPLE_RATE * 1.0), dtype=np.float32)
        sf.write(str(output_path), silence, _SAMPLE_RATE)
        return output_path

    segments = split_into_segments(text)
    pause = np.zeros(int(_SAMPLE_RATE * _PAUSE_MS / 1000), dtype=np.float32)

    pieces: list[np.ndarray] = []
    sr = _SAMPLE_RATE
    failures = 0
    for i, segment in enumerate(segments):
        expected_seconds = max(len(segment) / _CHARS_PER_SECOND, 3.0)
        audio, sr, ok = _synthesize_segment_with_gate(pipe, segment, speaker_audio, expected_seconds)
        if not ok:
            failures += 1
        if pieces:
            pieces.append(pause)
        pieces.append(audio)

    joined = np.concatenate(pieces) if pieces else np.zeros(int(sr * 1.0), dtype=np.float32)
    normalized = _loudness_normalize(joined, sr)
    sf.write(str(output_path), normalized, sr)
    logger.info(
        "Saved slide audio: %s (%.2fs, %d segments, %d failed gate)",
        output_path.name, len(normalized) / sr, len(segments), failures,
    )
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
