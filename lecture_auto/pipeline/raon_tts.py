"""Raon-Speech-9B TTS and STT module with voice cloning.

Supports:
1. Speech-to-Text (STT) for transcribing reference lectures and analyzing professor style.
2. Text-to-Speech (TTS) with speaker voice conditioning (ECAPA-TDNN embeddings) for voice cloning.
"""
from __future__ import annotations

import logging
import re
import tempfile
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
# Bump whenever the segmentation/join/gate algorithm changes (not just the
# model/temperature/seeds) -- content_hash() callers should include this so a
# pure code change (e.g. switching segment joins to tts_continuation) forces
# regeneration instead of silently reusing audio made by the old algorithm.
TTS_SYNTH_VERSION = "v6-split-retry-hard-gate"


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
    tuned = {
        "temperature": TTS_TEMPERATURE,
        "ras_enabled": True,
        "ras_window_size": 50,
        "ras_repetition_threshold": 0.5,
    }
    pipe.task_params["tts"].update(tuned)
    # tts_continuation (used to join segments after the first -- see
    # synthesize_raon_slide) needs the same tuning; it has its own task_params
    # entry in the model's defaults, identical to "tts" but independently set.
    pipe.task_params["tts_continuation"].update(tuned)
    logger.info("RaonPipeline loaded successfully (tts/tts_continuation task_params tuned: %s)", tuned)
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

# Quality gate thresholds, calibrated against 18 real generations (120-350
# char Korean text) manually classified good/bad by inspecting energy traces:
# good clips had voiced_ratio 0.56-0.64 and longest_silence <=1.85s; bad
# clips (long true-silence or quiet babble) had voiced_ratio <=0.35 and
# longest_silence >=4.6s. Thresholds sit in the gap between those clusters.
_MIN_VOICED_RATIO = 0.50
_MAX_DURATION_RATIO = 1.8
_MAX_INTERNAL_SILENCE_S = 2.5

# Lower duration bound: the gate used to only reject clips that ran LONG, so a
# generation that stopped after the first sentence of a three-sentence segment
# passed everything -- high voiced ratio, no long silence, short duration --
# and silently dropped the rest of the narration. Measured on lecture 01's 48
# slides: clean clips land at ~1.1x their char-derived estimate (real Korean
# rate is nearer 6.4 chars/s than the 7.0 estimate), while slide 009 spoke 291
# chars in 26.9s against a 41.6s estimate (0.65x) with a third of its script
# missing. 0.8 sits well below every clean clip and above that truncation.
_MIN_DURATION_RATIO = 0.8

# On gate failure, the same seeds regenerate bit-identically -- torch.manual_seed
# over a fixed TTS_SEEDS is deterministic, so retrying alone loops forever.
# Splitting the segment changes the text, which changes the draw, and shorter
# text is empirically what this model finishes cleanly (see the 250-char
# collapse note above). Two levels takes a 120-char segment down to ~30 chars.
_MAX_SPLIT_DEPTH = 2
# ~15 Korean chars is roughly 2.5s of speech -- still a generatable unit, and
# low enough that a 60-char segment can split twice before hitting the floor.
_MIN_SPLITTABLE_CHARS = 15

_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+")
# Clause boundaries used only when a failing segment is a single sentence with
# no sentence break to split on. Korean connective endings + comma.
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,،])\s+|(?<=고)\s+|(?<=며)\s+|(?<=만)\s+|(?<=서)\s+")


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


def split_in_half(text: str) -> list[str]:
    """Split a segment near its midpoint, preferring a sentence boundary.

    Returns ``[text]`` unchanged when there is no usable break or the halves
    would be too short to be worth generating separately. Used only as the
    escape hatch when every seed fails the quality gate on a segment.
    """
    text = text.strip()
    if len(text) < _MIN_SPLITTABLE_CHARS * 2:
        return [text]

    for pattern in (_SENTENCE_END_RE, _CLAUSE_SPLIT_RE):
        parts = [p.strip() for p in pattern.split(text) if p.strip()]
        if len(parts) < 2:
            continue
        # Pick the join point whose left side is closest to half the text.
        midpoint = len(text) / 2
        best_i, best_gap = 1, float("inf")
        for i in range(1, len(parts)):
            gap = abs(len(" ".join(parts[:i])) - midpoint)
            if gap < best_gap:
                best_gap, best_i = gap, i
        left = " ".join(parts[:best_i])
        right = " ".join(parts[best_i:])
        if len(left) >= _MIN_SPLITTABLE_CHARS and len(right) >= _MIN_SPLITTABLE_CHARS:
            return [left, right]
    return [text]


def _frame_energies(wav: np.ndarray, sr: int, frame_ms: float = 50) -> np.ndarray:
    frame_len = int(sr * frame_ms / 1000)
    if frame_len <= 0 or len(wav) < frame_len:
        return np.array([])
    n_frames = len(wav) // frame_len
    frames = wav[: n_frames * frame_len].reshape(n_frames, frame_len)
    return np.sqrt(np.mean(frames**2, axis=1))


# Voiced/silent classification is relative to each clip's own 90th-percentile
# frame energy, not a fixed absolute amplitude. A fixed threshold (e.g. 0.02)
# assumes raw model output sits at a consistent gain -- measured it doesn't:
# this model's raw (pre loudness-normalize) output for real segments ranged
# -28 to -41 LUFS, and a fixed 0.02 cutoff rejected clips whose own energy
# trace (verified by inspecting the raw per-window trace by eye) showed
# completely normal speech-then-pause patterns. Relative-to-self scales with
# whatever gain a given generation happened to come out at.
_RELATIVE_VOICED_THRESHOLD = 0.25


def _voiced_ratio(wav: np.ndarray, sr: int, frame_ms: float = 50) -> float:
    energies = _frame_energies(wav, sr, frame_ms)
    if len(energies) == 0:
        return 0.0
    p_speech = np.percentile(energies, 90)
    if p_speech < 1e-6:
        return 0.0
    return float(np.mean(energies >= _RELATIVE_VOICED_THRESHOLD * p_speech))


def _longest_silence_seconds(wav: np.ndarray, sr: int, frame_ms: float = 50) -> float:
    energies = _frame_energies(wav, sr, frame_ms)
    if len(energies) == 0:
        return 0.0
    p_speech = np.percentile(energies, 90)
    if p_speech < 1e-6:
        return len(wav) / sr
    silent = energies < _RELATIVE_VOICED_THRESHOLD * p_speech

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


def _passes_quality_gate(
    wav: np.ndarray, sr: int, expected_seconds: float, min_seconds: float = 0.0
) -> bool:
    """Content-quality gate on a segment's raw (pre-normalization) audio.

    No absolute loudness floor here: `synthesize_raon_slide` runs a single
    `_loudness_normalize` pass over the whole joined slide at the end, so a
    segment's native gain is corrected regardless -- gating on it too was
    measured to reject good speech. 2 of 6 samples in a live check had
    voiced_ratio/longest_silence within the content thresholds (0.38-0.47,
    1.2-2.0s) but were rejected purely because raw LUFS was -28 to -41,
    nowhere near a real quality signal. Kept `_integrated_lufs` only for
    `_loudness_normalize`'s own use.
    """
    if len(wav) == 0:
        return False
    duration = len(wav) / sr
    if duration > expected_seconds * _MAX_DURATION_RATIO:
        return False
    if duration < min_seconds:
        return False
    if _voiced_ratio(wav, sr) < _MIN_VOICED_RATIO:
        return False
    return _longest_silence_seconds(wav, sr) <= _MAX_INTERNAL_SILENCE_S


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
    continuation_ref: tuple[Path, str] | None = None,
) -> tuple[np.ndarray, int, bool]:
    """Synthesize one short segment, retrying with a different seed on gate failure.

    ``continuation_ref`` is ``(prev_segment_wav_path, prev_segment_text)``. When
    given, the segment is generated with ``pipe.tts_continuation()`` -- the
    model is prefilled with the previous segment's own audio as already-
    generated output and continues from there, keeping pitch/intonation
    continuous across the join instead of resetting per segment (confirmed
    empirically that the returned waveform is only the new continuation, not
    a copy of the prefilled reference -- correlation ~0 between the two).
    When ``None`` (first segment of a slide), falls back to plain ``tts()``.
    """
    task_key = "tts_continuation" if continuation_ref is not None else "tts"
    max_new_tokens = int(
        min(max(expected_seconds * _CODEC_FRAME_RATE * 1.4, _MIN_MAX_NEW_TOKENS), _MAX_MAX_NEW_TOKENS)
    )
    pipe.task_params[task_key]["max_new_tokens"] = max_new_tokens

    speaker_audio_str = str(speaker_audio) if speaker_audio is not None and Path(speaker_audio).exists() else None
    # Floor derived from the text itself, not from the 3.0s-floored
    # expected_seconds -- a very short trailing segment must not be required
    # to fill 3 seconds of speech.
    min_seconds = len(text) / _CHARS_PER_SECOND * _MIN_DURATION_RATIO

    best_fallback: tuple[np.ndarray, int] | None = None
    best_fallback_score = float("inf")  # longest internal silence/babble run, seconds -- lower is better
    for seed in TTS_SEEDS:
        torch.manual_seed(seed)
        try:
            if continuation_ref is not None:
                prev_wav_path, prev_text = continuation_ref
                audio_tensor, sr = pipe.tts_continuation(
                    target_text=text,
                    ref_audio=str(prev_wav_path),
                    ref_text=prev_text,
                    speaker_audio=speaker_audio_str,
                )
            else:
                kwargs = {"speaker_audio": speaker_audio_str} if speaker_audio_str else {}
                audio_tensor, sr = pipe.tts(text, **kwargs)
        except Exception:
            # modeling_raon.py's tts_continuation() has a known edge case where
            # generation produces no audio tokens and the model code does
            # `audio[0]` on a None result, raising an uncaught TypeError -- this
            # killed a multi-hour unattended batch run at slide 19/48. A bad
            # generation on one seed must not take down the whole job; try the
            # next seed instead.
            logger.warning("TTS call raised for seed %s (%s): %r", seed, task_key, text[:60], exc_info=True)
            continue
        trimmed = _trim_lead_tail_silence(_to_numpy(audio_tensor, sr), sr)
        if _passes_quality_gate(trimmed, sr, expected_seconds, min_seconds):
            return trimmed, sr, True
        # Keep the least-bad failed attempt as fallback, not just the first
        # one tried -- an early seed's babble shouldn't beat a later seed's
        # near-miss just because it went first. Score penalises truncation as
        # well as silence: ranking on silence alone would crown a clip that
        # stopped after one sentence (no silence, no content) over a complete
        # one with a single long pause, and losing narration is the worse of
        # the two failures.
        shortfall = max(0.0, min_seconds - len(trimmed) / sr)
        score = _longest_silence_seconds(trimmed, sr) + shortfall
        if score < best_fallback_score:
            best_fallback_score = score
            best_fallback = (trimmed, sr)

    if best_fallback is None:
        # Every seed raised -- no audio was ever produced for this segment.
        # Degrade to silence rather than crash; this is rare enough (first
        # observed once in ~150 segments) that losing one segment's worth of
        # narration is far cheaper than losing hours of an unattended batch.
        logger.error("All %d attempts raised for segment, using silence: %r", len(TTS_SEEDS), text[:60])
        silence = np.zeros(int(_SAMPLE_RATE * expected_seconds), dtype=np.float32)
        return silence, _SAMPLE_RATE, False

    logger.warning("Segment failed quality gate after seeds %s: %r", TTS_SEEDS, text[:60])
    return best_fallback[0], best_fallback[1], False


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

    When every seed fails the gate on a segment, the segment is split near its
    midpoint and the halves are retried (up to ``_MAX_SPLIT_DEPTH``) -- fixed
    seeds mean a plain retry regenerates the identical bad audio, so the text
    has to change for the draw to change.

    ``max_seconds`` is the slide's own script budget (``target_seconds``). The
    joined result is checked against it: per-segment gating alone let a slide
    accumulate many individually-tolerable overruns into a 2x-long clip.

    Returns ``(output_path, ok)``. ``ok`` is False when any segment failed its
    gate after splitting, or the joined slide blew its duration budget. The
    audio is still written either way -- an unattended multi-hour batch must
    not die over one bad slide -- but callers MUST NOT cache a False result,
    or the next run adopts the damaged audio as a valid artifact.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = text.strip()
    if not text:
        logger.debug("Empty text for slide -- generating 1s silence at %s", output_path)
        silence = np.zeros(int(_SAMPLE_RATE * 1.0), dtype=np.float32)
        sf.write(str(output_path), silence, _SAMPLE_RATE)
        return output_path, True

    segments = split_into_segments(text)
    pause = np.zeros(int(_SAMPLE_RATE * _PAUSE_MS / 1000), dtype=np.float32)

    pieces: list[np.ndarray] = []
    sr = _SAMPLE_RATE
    failures = 0
    generated = 0
    with tempfile.TemporaryDirectory(prefix="raon_seg_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        continuation_ref: tuple[Path, str] | None = None
        pending: list[tuple[str, int]] = [(seg, 0) for seg in reversed(segments)]

        while pending:
            segment, depth = pending.pop()
            expected_seconds = max(len(segment) / _CHARS_PER_SECOND, 3.0)
            audio, sr, ok = _synthesize_segment_with_gate(
                pipe, segment, speaker_audio, expected_seconds, continuation_ref=continuation_ref
            )

            if not ok and depth < _MAX_SPLIT_DEPTH:
                halves = split_in_half(segment)
                if len(halves) == 2:
                    logger.info(
                        "Segment failed at depth %d, splitting %d chars -> %d + %d and retrying",
                        depth, len(segment), len(halves[0]), len(halves[1]),
                    )
                    pending.extend((h, depth + 1) for h in reversed(halves))
                    continue

            if not ok:
                failures += 1
            if pieces:
                pieces.append(pause)
            pieces.append(audio)
            generated += 1

            # Only a segment that passed its gate becomes the prosody reference
            # for the next one. Prefilling tts_continuation with silence or with
            # a collapsed generation propagates that collapse forward; holding
            # the last good reference keeps the voice steady instead.
            if ok:
                seg_path = tmp_dir_path / f"seg_{generated:03d}.wav"
                sf.write(str(seg_path), audio, sr)
                continuation_ref = (seg_path, segment)

        joined = np.concatenate(pieces) if pieces else np.zeros(int(sr * 1.0), dtype=np.float32)

    normalized = _loudness_normalize(joined, sr)
    sf.write(str(output_path), normalized, sr)

    duration = len(normalized) / sr
    over_budget = max_seconds is not None and duration > max_seconds * _MAX_DURATION_RATIO
    if over_budget:
        logger.warning(
            "Slide audio %s ran %.1fs against a %.1fs budget (>%.1fx) -- marking failed",
            output_path.name, duration, max_seconds, _MAX_DURATION_RATIO,
        )
    ok = failures == 0 and not over_budget
    logger.info(
        "Saved slide audio: %s (%.2fs, %d segments, %d failed gate, ok=%s)",
        output_path.name, duration, generated, failures, ok,
    )
    return output_path, ok


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
        _, ok = synthesize_raon_slide(
            pipe, text, out_path, speaker_audio=speaker_audio,
            max_seconds=slide.get("target_seconds"),
        )
        if not ok:
            logger.warning("Slide %d audio failed quality gate", i)
        wav_paths.append(out_path)

    logger.info("Synthesized %d slide audios in %s", len(wav_paths), audio_dir)
    return wav_paths
