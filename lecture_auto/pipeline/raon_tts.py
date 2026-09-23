"""Raon-Speech-9B TTS and STT module with voice cloning.

Supports:
1. Speech-to-Text (STT) for transcribing reference lectures and analyzing professor style.
2. Text-to-Speech (TTS) with speaker voice conditioning (ECAPA-TDNN embeddings) for voice cloning.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
import torch

from lecture_auto.pipeline.cache import qc_path_for, write_text_atomic
from lecture_auto.schemas.production import SegmentQC, SlideQC, TranscriptionCheck

logger = logging.getLogger(__name__)

# TranscriptionCheck is re-exported from schemas/production.py (S6-a moved it
# there); `from lecture_auto.pipeline.raon_tts import TranscriptionCheck`
# keeps working for existing callers (S4-a review follow-up).

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
TTS_SYNTH_VERSION = "v11-sweetspot-80-100"


def load_raon_pipeline(
    model_id: str = _DEFAULT_MODEL_ID,
    device: str = "cuda:0",
    dtype: str = "bfloat16",
):
    """Load RaonPipeline from HuggingFace Hub or local cache."""
    from transformers import AutoConfig
    from transformers.dynamic_module_utils import get_class_from_dynamic_module

    logger.info("Loading RaonPipeline from %s on %s (%s)", model_id, device, dtype)

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


def _stt_content_reasons(trans_clean: str, exp_clean: str) -> list[str]:
    """Repetition-loop and length-discrepancy checks shared by the gate.

    1. Repetition loops (hallucination babble / word repetition).
    2. Severe truncation or runaway length discrepancy in transcribed text.

    Both inputs are expected to already be whitespace-collapsed and non-empty.
    """
    reasons: list[str] = []

    # 1. Repetition loop detection (same word or 2-word phrase repeated consecutively)
    words = trans_clean.split()
    if len(words) >= 3:
        for i in range(len(words) - 2):
            if words[i] == words[i + 1] == words[i + 2]:
                reasons.append(f"stt_repetition({words[i]!r}*3)")
                break
            if i + 3 < len(words) and words[i : i + 2] == words[i + 2 : i + 4]:
                reasons.append(f"stt_phrase_loop({' '.join(words[i:i+2])!r})")
                break

    # 2. Transcribed length discrepancy (< 55% or > 160% of expected characters)
    ratio = len(trans_clean) / max(len(exp_clean), 1)
    if ratio < 0.55:
        reasons.append(f"stt_short({ratio:.2f})")
    elif ratio > 1.60:
        reasons.append(f"stt_long({ratio:.2f})")

    return reasons


_CER_STRIP_RE = re.compile(r"[\s.,!?·…\"'()\[\]]")


def _normalize_for_cer(text: str) -> str:
    """Normalize text for character error rate comparison.

    Rules (spec SPEC_S4a.md): strip all whitespace, strip the punctuation set
    ``.,!?·…"'()[]``, then ``.lower()`` (only affects cased letters, e.g. any
    stray Latin text mixed into a Korean script; Korean syllables have no
    case and are unaffected). Only the literal punctuation set the spec
    lists is stripped -- other marks (curly quotes, colons, dashes, etc.)
    are intentionally left in place; broadening this to
    ``unicodedata.category(ch)[0] == "P"`` would be a reasonable follow-up
    if real transcripts show CER inflated by punctuation outside this set.
    """
    return _CER_STRIP_RE.sub("", text).lower()


def _levenshtein(a: str, b: str) -> int:
    """Minimal character edit distance (insert/delete/substitute), O(len(a)*len(b)).

    A true DP, not a difflib-style longest-common-subsequence diff: difflib's
    opcodes are not guaranteed to be the minimum edit count.
    """
    if a == b:
        return 0
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        ai = a[i - 1]
        for j in range(1, n + 1):
            cost = 0 if ai == b[j - 1] else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n]


def compute_cer(reference: str, hypothesis: str) -> float | None:
    """Character Error Rate = edit_distance(ref, hyp) / len(ref), after normalization.

    Returns ``None`` when the normalized reference is empty (CER is undefined).
    """
    ref_norm = _normalize_for_cer(reference)
    if not ref_norm:
        return None
    hyp_norm = _normalize_for_cer(hypothesis)
    return _levenshtein(ref_norm, hyp_norm) / len(ref_norm)


def evaluate_transcription(
    pipe,
    audio_path: str | Path,
    expected_text: str,
) -> TranscriptionCheck:
    """Run the STT fidelity check and report status/reasons/transcript/CER.

    ``status`` is ``"unavailable"`` when STT itself failed or either the
    transcript or expected text is empty (fidelity could not be judged),
    ``"fail"`` when content-fidelity reasons were found, otherwise ``"pass"``.
    ``cer`` is recorded for visibility only (D-08: no pass/fail threshold) and
    is ``None`` whenever it can't be computed.
    """
    try:
        transcribed = transcribe_audio(pipe, audio_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("STT transcription failed during fidelity check: %s", e)
        return TranscriptionCheck(status="unavailable", reasons=[], transcript=None, cer=None)

    trans_clean = re.sub(r"\s+", " ", transcribed).strip()
    exp_clean = re.sub(r"\s+", " ", expected_text).strip()
    if not trans_clean or not exp_clean:
        return TranscriptionCheck(
            status="unavailable", reasons=[], transcript=transcribed or None, cer=None
        )

    reasons = _stt_content_reasons(trans_clean, exp_clean)
    cer = compute_cer(expected_text, transcribed)
    status: Literal["pass", "fail"] = "fail" if reasons else "pass"
    return TranscriptionCheck(status=status, reasons=reasons, transcript=transcribed, cer=cer)


def check_transcription_fidelity(
    pipe,
    audio_path: str | Path,
    expected_text: str,
) -> list[str]:
    """Check synthesized audio against script using Raon-Speech-9B STT.

    Thin wrapper over :func:`evaluate_transcription` kept for existing
    callers: same return value (``reasons``) for every input as before.
    """
    return evaluate_transcription(pipe, audio_path, expected_text).reasons


def _trim_lead_tail_silence(wav: np.ndarray, sr: int = _SAMPLE_RATE) -> np.ndarray:
    """Trim excessive lead/tail silence, keeping a small natural pad.

    The cutoff is relative to the clip's own loud frames, matching how the
    quality gate classifies silence. A fixed absolute threshold (0.005) left
    quiet babble at 0.008 in place: too quiet to be trimmed, but still
    "silence" to the gate, so two joined fragments contributed their untrimmed
    edges plus the join pause as one long contiguous silent run.
    """
    if len(wav) == 0:
        return wav

    peak_ref = np.percentile(np.abs(wav), 95)
    threshold = max(0.005, float(peak_ref) * _RELATIVE_VOICED_THRESHOLD)
    active = np.where(np.abs(wav) > threshold)[0]
    if len(active) == 0:
        return wav
    start = max(0, active[0] - int(sr * 0.05))
    end = min(len(wav), active[-1] + int(sr * 0.05))
    return wav[start:end]


_CODEC_FRAME_RATE = 12.5  # Mimi codec, verified in modeling_raon.py
# The cap has to scale with the text. A flat 300-token floor is ~24s of audio,
# which for a 19-char segment (3.3s of speech) is 7x more room than it needs --
# and a generation that has collapsed spends the whole allowance babbling. The
# floor only ever mattered before the text was segmented; no segment needs 24s.
# Ceiling sized off the longest segment split_into_segments actually emits
# (147 chars measured on lecture 04, needing ~492 tokens), not off a round
# number: too low silently truncates real narration, which is the worse failure.
_MIN_MAX_NEW_TOKENS = 64  # ~5.1s, enough for the shortest split fragment
_MAX_MAX_NEW_TOKENS = 640  # ~51s, comfortably over the longest real segment

# A single pipe.tts() call over a whole 250+ char slide script is what was
# collapsing into long silent runs / runaway babble (measured: up to 82%
# internal silence, 122s output for a ~35s target). Splitting into short
# 1-2 sentence segments, gating each one, and retrying with a different seed
# on failure keeps every clip short enough for the model to actually finish
# its sentence and stop.
# Segmenting sweet spot calibrated from real batches (60-80 chars fails 36%
# mostly by truncation, 100-130 chars fails 35% by runaway babble/hallucination,
# while 80-100 chars achieves optimal 15% failure rate).
_SEGMENT_MIN_CHARS = 75
_SEGMENT_MAX_CHARS = 105
# Measured rendering rate of THIS model on the cloned voice -- two gate-passing
# v7 generations came out at 5.52 and 5.84 chars/s. Not the professor's own rate
# (6.46 chars/s over his 32min recording); only the TTS rate sets video length.
# Must stay in sync with SPEECH_CHARS_PER_SECOND in script_gen.py: the scripts
# are budgeted at this rate and the gate's duration window is sized by it, so a
# mismatch either loosens the gate or makes every clean clip look overlong.
_CHARS_PER_SECOND = 5.7
_PAUSE_MS = 200
# Order matters and the first three must not move: they are what the shipped
# lecture-01 audio was drawn from, so a slide that passed on one of them
# regenerates byte-identically and its cache stays honest. The extra two exist
# because a re-run is otherwise pointless -- seeding is deterministic, so a
# failing slide redrawn from the same three fails identically forever.
TTS_SEEDS = (17, 29, 43, 61, 79)
_TARGET_LUFS = -20.0

# Calibrated quality gate thresholds:
# Voiced ratio 0.45, max internal silence tightened to 2.8s (catches slide 023's
# 3.8s and slide 048's 5.0s dead air), max duration ratio tightened from 1.8 to
# 1.35 (catches babble/stretching hallucination in overlong segments), and min
# duration ratio raised from 0.70 to 0.78 (catches truncation/early stop in slide 041).
_MIN_VOICED_RATIO = 0.45
_MAX_DURATION_RATIO = 1.35
_MAX_INTERNAL_SILENCE_S = 2.8

# Lower duration bound: catches lost narration when generation terminates early.
# 0.78 catches truncation (such as slide 041 stopping ~26% short) while allowing
# naturally fast delivery.
_MIN_DURATION_RATIO = 0.78

# On gate failure, the same seeds regenerate bit-identically -- torch.manual_seed
# over a fixed TTS_SEEDS is deterministic, so retrying alone loops forever.
# Splitting the segment changes the text, which changes the draw, and shorter
# text is empirically what this model finishes cleanly (see the 250-char
# collapse note above). Two levels takes a 120-char segment down to ~30 chars.
# One level, not two. Each level multiplies generations: a failing 120-char
# segment costs 4 draws, then 4 per half, and at depth 2 another 4 per quarter
# -- 28 generations for one segment, which is where the batch's time went.
# Depth 2 also produces ~30-char fragments whose own gate is the least reliable,
# so the extra level was buying retries that mostly failed anyway.
_MAX_SPLIT_DEPTH = 1
# ~15 Korean chars is roughly 2.5s of speech -- still a generatable unit, and
# low enough that a 60-char segment can split twice before hitting the floor.
_MIN_SPLITTABLE_CHARS = 15
# Splitting an already-short segment adds draws without adding much of a
# different draw; failures below this are better reported than retried. Set at
# the normal segment floor, not higher: a 74-char two-sentence segment splits
# cleanly at its sentence boundary into two usable halves, and depth 1 has
# already capped the cost multiplication that made splitting expensive.
_MIN_SPLIT_WORTH_CHARS = 60

_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+")
# Clause boundaries used only when a failing segment is a single sentence with
# no sentence break to split on. Korean connective endings + comma.
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,،])\s+|(?<=고)\s+|(?<=며)\s+|(?<=만)\s+|(?<=서)\s+")


def _to_numpy(audio_tensor, sr_fallback: int = _SAMPLE_RATE) -> np.ndarray:
    if hasattr(audio_tensor, "squeeze"):
        return audio_tensor.squeeze().cpu().float().numpy()
    return np.array(audio_tensor, dtype=np.float32)


def _split_long_sentence(text: str, max_chars: int = _SEGMENT_MAX_CHARS) -> list[str]:
    """Split a single sentence longer than max_chars at clause boundaries."""
    text = text.strip()
    if len(text) <= max_chars:
        return [text]
    parts = [p.strip() for p in _CLAUSE_SPLIT_RE.split(text) if p.strip()]
    if len(parts) < 2:
        return [text]
    pieces: list[str] = []
    curr = ""
    for p in parts:
        if not curr:
            curr = p
            continue
        cand = f"{curr} {p}"
        if len(cand) <= max_chars:
            curr = cand
        else:
            pieces.append(curr)
            curr = p
    if curr:
        pieces.append(curr)
    return pieces


def split_into_segments(
    script: str,
    min_chars: int = _SEGMENT_MIN_CHARS,
    max_chars: int = _SEGMENT_MAX_CHARS,
) -> list[str]:
    """Group a script's sentences into ~75-105 char TTS-sweetspot segments.

    Splits overlong single sentences at clause boundaries, and groups sentences
    into the calibrated 80-100 char sweet spot to prevent both early truncation
    (<60-80 chars) and runaway babble/hallucination (>100 chars).
    """
    raw_sentences = [s.strip() for s in _SENTENCE_END_RE.split(script.strip()) if s.strip()]
    sentences: list[str] = []
    for sent in raw_sentences:
        if len(sent) > max_chars:
            sentences.extend(_split_long_sentence(sent, max_chars=max_chars))
        else:
            sentences.append(sent)

    segments: list[str] = []
    current = ""
    for sent in sentences:
        if not current:
            current = sent
            continue
        candidate = f"{current} {sent}"
        if len(candidate) <= max_chars or (len(current) < min_chars and len(candidate) <= max_chars + 10):
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


def _speech_reference(wav: np.ndarray, sr: int, frame_ms: float = 50) -> float:
    """The 90th-percentile frame energy a clip should be judged against.

    Passing this from the whole slide into a single segment's check is what
    makes the segment gate able to see a uniformly quiet generation. Judged
    against itself, such a segment is fully voiced; judged against the slide's
    real speech, it is the dead air a listener hears.
    """
    energies = _frame_energies(wav, sr, frame_ms)
    return float(np.percentile(energies, 90)) if len(energies) else 0.0


def _voiced_ratio(
    wav: np.ndarray, sr: int, frame_ms: float = 50, reference: float | None = None
) -> float:
    energies = _frame_energies(wav, sr, frame_ms)
    if len(energies) == 0:
        return 0.0
    p_speech = float(np.percentile(energies, 90)) if reference is None else reference
    if p_speech < 1e-6:
        return 0.0
    return float(np.mean(energies >= _RELATIVE_VOICED_THRESHOLD * p_speech))


def _longest_silence_seconds(
    wav: np.ndarray, sr: int, frame_ms: float = 50, reference: float | None = None
) -> float:
    energies = _frame_energies(wav, sr, frame_ms)
    if len(energies) == 0:
        return 0.0
    p_speech = float(np.percentile(energies, 90)) if reference is None else reference
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
    wav: np.ndarray,
    sr: int,
    expected_seconds: float,
    min_seconds: float = 0.0,
    energy_reference: float | None = None,
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
    if _voiced_ratio(wav, sr, reference=energy_reference) < _MIN_VOICED_RATIO:
        return False
    return _longest_silence_seconds(wav, sr, reference=energy_reference) <= _MAX_INTERNAL_SILENCE_S


def _slide_gate_failures(
    wav: np.ndarray, sr: int, char_count: int, max_seconds: float | None
) -> list[str]:
    """Gate the joined slide, naming every reason it should not be cached.

    Separate from `_passes_quality_gate` because it answers a different
    question. That one ranks candidate generations for one segment; this one
    decides whether the artifact is fit to ship. Run on the joined wav, the
    relative energy threshold is set by the slide's real speech, so a segment
    that is only quiet next to its neighbours finally shows up as the silence
    a listener would hear.
    """
    reasons = []
    duration = len(wav) / sr
    expected = char_count / _CHARS_PER_SECOND
    if max_seconds is not None and duration > max_seconds * _MAX_DURATION_RATIO:
        reasons.append(f"long({duration:.0f}s>{max_seconds:.0f}s)")
    if duration < expected * _MIN_DURATION_RATIO:
        reasons.append(f"short({duration:.0f}s<{expected * _MIN_DURATION_RATIO:.0f}s)")
    voiced = _voiced_ratio(wav, sr)
    if voiced < _MIN_VOICED_RATIO:
        reasons.append(f"voiced({voiced:.2f})")
    silence = _longest_silence_seconds(wav, sr)
    if silence > _MAX_INTERNAL_SILENCE_S:
        reasons.append(f"silence({silence:.1f}s)")
    return reasons


def _loudness_normalize(wav: np.ndarray, sr: int, target_lufs: float = _TARGET_LUFS) -> np.ndarray:
    loudness = _integrated_lufs(wav, sr)
    if not np.isfinite(loudness):
        return wav.astype(np.float32)
    normalized = pyln.normalize.loudness(wav.astype(np.float64), loudness, target_lufs)
    peak = np.max(np.abs(normalized))
    if peak > 1.0:
        normalized = normalized / peak * 0.98
    return normalized.astype(np.float32)


# Set RAON_TRACE to a path to record one JSON line per generation call. Off by
# default: this is diagnostic instrumentation, not something a batch should pay
# for. Records only what the call actually reports -- there is deliberately no
# token count here, because the pipeline returns a waveform and inferring
# tokens from its duration would be a guess dressed up as a measurement.
_TRACE_PATH = os.environ.get("RAON_TRACE")


def _trace(**fields) -> None:
    if not _TRACE_PATH:
        return
    try:
        with open(_TRACE_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(fields, ensure_ascii=False) + "\n")
    except OSError:  # tracing must never take down a batch
        logger.debug("trace write failed", exc_info=True)


def plan_attempts(has_continuation: bool) -> list[tuple[int, bool]]:
    """The (seed, use_continuation) draws to try, in order, for one segment.

    Two continuation draws, then plain tts. When tts_continuation fails on a
    (text, prefill) pair it fails on every seed -- a batch's crashes repeated
    identically across all of them, and plain tts() has never raised once.
    Spending the remaining draws on continuation is the most expensive thing
    this module can do and it has never once paid off.
    """
    if has_continuation:
        return [
            (TTS_SEEDS[0], True),
            (TTS_SEEDS[1], True),
            (TTS_SEEDS[2], False),
            (TTS_SEEDS[3], False),
        ]
    return [(seed, False) for seed in TTS_SEEDS[:4]]


def _synthesize_segment_with_gate(
    pipe,
    text: str,
    speaker_audio: Path | str | None,
    expected_seconds: float,
    continuation_ref: tuple[Path, str] | None = None,
    energy_reference: float | None = None,
    depth: int = 0,
    record: dict | None = None,
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

    ``record`` (S6-a), if given, is mutated in place with ``{"seed": ...,
    "call": "tts" | "tts_continuation" | None}`` for whichever attempt is
    actually returned (the passing one, or the least-bad fallback) -- this is
    how the caller learns *which* draw was kept without changing this
    function's return shape, which existing tests unpack as a plain 3-tuple.
    ``seed``/``call`` are ``None`` only when every attempt raised.
    """
    # +8 tokens of slack for the audio-end marker so a clip that is exactly
    # long enough is not cut off mid-word by its own budget.
    max_new_tokens = int(
        min(
            max(math.ceil(expected_seconds * _CODEC_FRAME_RATE * 1.5) + 8, _MIN_MAX_NEW_TOKENS),
            _MAX_MAX_NEW_TOKENS,
        )
    )
    # Both task entries: a segment that starts on tts_continuation can fall back
    # to plain tts mid-loop, and the cap has to follow it there.
    for key in ("tts", "tts_continuation"):
        pipe.task_params[key]["max_new_tokens"] = max_new_tokens

    speaker_audio_str = str(speaker_audio) if speaker_audio is not None and Path(speaker_audio).exists() else None
    # Floor derived from the text itself, not from the 3.0s-floored
    # expected_seconds -- a very short trailing segment must not be required
    # to fill 3 seconds of speech.
    min_seconds = len(text) / _CHARS_PER_SECOND * _MIN_DURATION_RATIO

    best_fallback: tuple[np.ndarray, int] | None = None
    best_fallback_score = float("inf")  # longest internal silence/babble run, seconds -- lower is better
    best_fallback_attempt: tuple[int, bool] | None = None  # (seed, use_continuation) that produced it
    # Spend two seeds on continuation, then stop asking it. When
    # tts_continuation fails on a (text, prefill) pair it fails on every seed --
    # all three of a batch's crashes repeated identically across seeds, and
    # plain tts() has never once raised. Three more continuation draws is the
    # single most expensive thing this function can do and it has never paid.
    # Dropping the prefill costs only the join smoothness on that one segment.
    attempts = plan_attempts(continuation_ref is not None)

    for seed, use_continuation in attempts:
        torch.manual_seed(seed)
        started = time.monotonic()
        try:
            if use_continuation and continuation_ref is not None:
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
            logger.warning(
                "TTS call raised for seed %s (%s): %r",
                seed, "tts_continuation" if use_continuation else "tts", text[:60], exc_info=True,
            )
            _trace(
                event="attempt", call="tts_continuation" if use_continuation else "tts",
                seed=seed, depth=depth, chars=len(text), max_new_tokens=max_new_tokens,
                seconds=round(time.monotonic() - started, 2), outcome="raised",
            )
            continue
        trimmed = _trim_lead_tail_silence(_to_numpy(audio_tensor, sr), sr)
        passed = _passes_quality_gate(trimmed, sr, expected_seconds, min_seconds, energy_reference)
        _trace(
            event="attempt", call="tts_continuation" if use_continuation else "tts",
            seed=seed, depth=depth, chars=len(text), max_new_tokens=max_new_tokens,
            seconds=round(time.monotonic() - started, 2),
            out_seconds=round(len(trimmed) / sr, 2), outcome="pass" if passed else "gate_fail",
        )
        if passed:
            if record is not None:
                record["seed"] = seed
                record["call"] = "tts_continuation" if use_continuation else "tts"
            return trimmed, sr, True
        # Keep the least-bad failed attempt as fallback, not just the first
        # one tried -- an early seed's babble shouldn't beat a later seed's
        # near-miss just because it went first. Score penalises truncation as
        # well as silence: ranking on silence alone would crown a clip that
        # stopped after one sentence (no silence, no content) over a complete
        # one with a single long pause, and losing narration is the worse of
        # the two failures.
        shortfall = max(0.0, min_seconds - len(trimmed) / sr)
        score = _longest_silence_seconds(trimmed, sr, reference=energy_reference) + shortfall
        if score < best_fallback_score:
            best_fallback_score = score
            best_fallback = (trimmed, sr)
            best_fallback_attempt = (seed, use_continuation)

    if best_fallback is None:
        # Every seed raised -- no audio was ever produced for this segment.
        # Degrade to silence rather than crash; this is rare enough (first
        # observed once in ~150 segments) that losing one segment's worth of
        # narration is far cheaper than losing hours of an unattended batch.
        logger.error("All %d attempts raised for segment, using silence: %r", len(attempts), text[:60])
        silence = np.zeros(int(_SAMPLE_RATE * expected_seconds), dtype=np.float32)
        if record is not None:
            record["seed"] = None
            record["call"] = None
        return silence, _SAMPLE_RATE, False

    logger.warning("Segment failed quality gate after %d attempts: %r", len(attempts), text[:60])
    if record is not None and best_fallback_attempt is not None:
        fb_seed, fb_use_continuation = best_fallback_attempt
        record["seed"] = fb_seed
        record["call"] = "tts_continuation" if fb_use_continuation else "tts"
    return best_fallback[0], best_fallback[1], False


class _SplitState:
    """Scratch dir + counter for the temp wavs tts_continuation needs as prefill."""

    def __init__(self, tmp_dir: Path):
        self.tmp_dir = tmp_dir
        self.n = 0

    def save_ref(self, audio: np.ndarray, sr: int, text: str) -> tuple[Path, str]:
        self.n += 1
        path = self.tmp_dir / f"seg_{self.n:04d}.wav"
        sf.write(str(path), audio, sr)
        return path, text


def _meta_for_leaf(record: dict, continuation_ref, own_path, fallback: bool) -> dict:
    """Build one S6-a piece-metadata dict from a ``_synthesize_segment_with_gate``
    ``record`` (``{"seed": ..., "call": ...}``).

    ``continuation_from_path`` is the *path* of the ref actually used --
    resolved to a ``SegmentQC.continuation_from`` index only once the whole
    slide's piece list is final (see ``synthesize_raon_slide``), because a
    piece's final index isn't known while generation is still in progress and
    a split can discard already-generated children (see docstring below).
    """
    used_continuation = record.get("call") == "tts_continuation"
    return {
        "seed": record.get("seed"),
        "call": record.get("call"),
        "fallback": fallback,
        "continuation_from_path": continuation_ref[0] if (used_continuation and continuation_ref is not None) else None,
        "own_path": own_path,
    }


def _synthesize_with_splitting(
    pipe,
    text: str,
    speaker_audio: Path | str | None,
    continuation_ref: tuple[Path, str] | None,
    depth: int,
    state: _SplitState,
    metas: list[dict] | None = None,
) -> tuple[list[tuple[str, np.ndarray, int]], bool, tuple[Path, str] | None]:
    """Synthesize one segment, splitting and retrying only if that actually helps.

    Each returned piece carries the text it was actually generated from, which
    is the *half* after a split, not the parent. Returning audio alone let the
    caller label both halves with the whole parent text; redrawing one half
    then synthesized the parent and dropped it into the half's slot, so the
    slide read the second half twice.

    Returns ``(pieces, ok, continuation_ref)``.

    The split is accepted only when *every* child passes its gate. Appending
    failed children unconditionally multiplied the damage instead of repairing
    it: one segment failing at depth 0 became two failing children, then four
    leaves, and all four least-bad fallbacks were concatenated -- measured on
    slide 009, 26.9s of bad audio became 66.3s of it. Falling back to the
    parent's own single best attempt caps a failure at exactly what it cost
    before splitting existed, while keeping the full benefit when a split does
    produce clean children.

    ``metas`` (S6-a), if given, gets exactly one dict appended per entry in
    the *returned* pieces list, in the same order -- so callers pair
    ``metas[i]`` with the piece at the same position without needing a
    parallel index scheme through the recursion. When a split is attempted
    but discarded (one child failed), the children's own metas are dropped
    along with their audio -- they were never part of the output, so
    recording them would describe generations the final WAV never contains.
    """
    expected_seconds = max(len(text) / _CHARS_PER_SECOND, 3.0)
    record: dict = {}
    audio, sr, ok = _synthesize_segment_with_gate(
        pipe, text, speaker_audio, expected_seconds, continuation_ref=continuation_ref, depth=depth, record=record
    )
    if ok:
        # Only a passing segment becomes the prosody reference for the next
        # one. Prefilling tts_continuation with a collapsed generation
        # propagates that collapse forward.
        ref = state.save_ref(audio, sr, text)
        if metas is not None:
            metas.append(_meta_for_leaf(record, continuation_ref, ref[0], fallback=False))
        return [(text, audio, sr)], True, ref

    # Below this a split is not worth attempting: the halves are too short to
    # be judged reliably and each one still costs a full set of draws.
    splittable = len(text) > _MIN_SPLIT_WORTH_CHARS
    halves = split_in_half(text) if depth < _MAX_SPLIT_DEPTH and splittable else [text]
    if len(halves) != 2:
        if metas is not None:
            metas.append(_meta_for_leaf(record, continuation_ref, None, fallback=True))
        return [(text, audio, sr)], False, continuation_ref

    logger.info(
        "Segment failed at depth %d, splitting %d chars -> %d + %d and retrying",
        depth, len(text), len(halves[0]), len(halves[1]),
    )
    child_pieces: list[tuple[str, np.ndarray, int]] = []
    child_metas: list[dict] = []
    child_ref = continuation_ref
    all_ok = True
    for half in halves:
        got, child_ok, child_ref = _synthesize_with_splitting(
            pipe, half, speaker_audio, child_ref, depth + 1, state, metas=child_metas
        )
        child_pieces.extend(got)
        if not child_ok:
            # The split is only accepted if every child passes, so once one
            # fails the rest of this subtree is generation we will discard.
            # At ~45s per attempt that is worth short-circuiting.
            all_ok = False
            break

    if all_ok:
        if metas is not None:
            metas.extend(child_metas)
        return child_pieces, True, child_ref
    logger.warning(
        "Split of %d chars did not produce clean halves -- keeping the parent's best attempt",
        len(text),
    )
    if metas is not None:
        # Same first-attempt record as the len(halves) != 2 branch above --
        # this is the parent's own pre-split draw, kept because the split
        # attempt was discarded.
        metas.append(_meta_for_leaf(record, continuation_ref, None, fallback=True))
    return [(text, audio, sr)], False, continuation_ref


def _write_slide_qc(
    qc_path: Path,
    *,
    ok: bool,
    gate_reasons: list[str],
    stt,
    spoken_text: str,
    segments: list[SegmentQC],
    boundary_review: list[int],
) -> None:
    """Write ``qc_path`` atomically as a ``SlideQC`` (S6-a)."""
    qc = SlideQC(
        ok=ok,
        gate_reasons=gate_reasons,
        stt=stt,
        spoken_text_sha256=hashlib.sha256(spoken_text.encode("utf-8")).hexdigest(),
        segments=segments,
        boundary_review=boundary_review,
        synth_version=TTS_SYNTH_VERSION,
        created_at=datetime.now(timezone.utc),
    )
    write_text_atomic(qc_path, qc.model_dump_json(indent=2))


def synthesize_raon_slide(
    pipe,
    text: str,
    output_path: Path,
    speaker_audio: Path | str | None = None,
    max_seconds: float | None = None,
    verify_stt: bool = False,
    qc_path: Path | None = None,
) -> tuple[Path, bool]:
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

    ``qc_path`` (S6-a), if given, gets a ``SlideQC`` written atomically next
    to the audio -- segment-level seed/call/continuation bookkeeping (F1) and,
    when the second pass below actually replaces a piece another piece was
    already generated as a ``tts_continuation`` of, that downstream piece's
    index in ``boundary_review`` (F6) for a human to re-listen to. ``None``
    (the default) writes nothing, matching every existing caller.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = text.strip()
    if not text:
        logger.debug("Empty text for slide -- generating 1s silence at %s", output_path)
        silence = np.zeros(int(_SAMPLE_RATE * 1.0), dtype=np.float32)
        sf.write(str(output_path), silence, _SAMPLE_RATE)
        if qc_path is not None:
            _write_slide_qc(
                qc_path, ok=True, gate_reasons=[], stt=None,
                spoken_text=text, segments=[], boundary_review=[],
            )
        return output_path, True

    segments = split_into_segments(text)
    pause = np.zeros(int(_SAMPLE_RATE * _PAUSE_MS / 1000), dtype=np.float32)

    pieces: list[np.ndarray] = []
    seg_spans: list[tuple[str, int]] = []  # (text, index into pieces)
    metas: list[dict] = []  # S6-a: one entry per seg_spans entry, same order
    sr = _SAMPLE_RATE
    failures = 0
    generated = 0
    substituted = 0
    redraws = 0
    redraws_adopted = 0
    redraw_seconds = 0.0
    adopted_redraw_indices: set[int] = set()
    slide_started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="raon_seg_") as tmp_dir:
        state = _SplitState(Path(tmp_dir))
        continuation_ref: tuple[Path, str] | None = None

        for segment in segments:
            seg_pieces, ok, continuation_ref = _synthesize_with_splitting(
                pipe, segment, speaker_audio, continuation_ref, depth=0, state=state, metas=metas
            )
            if not ok:
                failures += 1
            for piece_text, audio, seg_sr in seg_pieces:
                if pieces:
                    pieces.append(pause)
                pieces.append(audio)
                sr = seg_sr
                generated += 1
                # Exactly-zero audio only comes from the all-seeds-raised path
                # in _synthesize_segment_with_gate; real generations are never
                # digitally silent. That substitution drops a whole sentence of
                # narration, so it fails the slide however the joined wav reads.
                # piece_text, not segment: after a split these are halves, and
                # labelling them with the parent is what made a redraw of one
                # half re-speak the whole thing.
                seg_spans.append((piece_text, len(pieces) - 1))
                if audio.size and not np.any(audio):
                    substituted += 1

        joined = np.concatenate(pieces) if pieces else np.zeros(int(sr * 1.0), dtype=np.float32)

        # S6-a/F6: resolve each piece's continuation_from *index* now, before
        # the redraw pass below can replace a piece -- path-matched (not
        # "index - 1") because a failed leaf doesn't update the continuation
        # chain, so the next piece's real ref can be more than one slot back.
        # Only pieces that actually made it into the output have "own_path"
        # set (see _synthesize_with_splitting/_meta_for_leaf), so a discarded
        # split child's orphaned ref path simply matches nothing here.
        path_to_index = {m["own_path"]: i for i, m in enumerate(metas) if m.get("own_path") is not None}
        for m in metas:
            m["continuation_from"] = path_to_index.get(m.get("continuation_from_path"))

        # Second pass. A segment's own gate compares it against itself, so a
        # uniformly quiet generation always passes and never consumes a retry
        # -- that is why slides 018/019/038 came back byte-identical no matter
        # how many seeds were added. Now that the whole slide exists, re-judge
        # each segment against the slide's real speech level and redraw the
        # ones that are only quiet next to their neighbours.
        reference = _speech_reference(joined, sr)
        if reference > 1e-6:
            for leaf_idx, (seg_text, idx) in enumerate(seg_spans):
                piece = pieces[idx]
                quiet = _voiced_ratio(piece, sr, reference=reference)
                gap = _longest_silence_seconds(piece, sr, reference=reference)
                # Both checks, not just the ratio. Slide 018 of lecture 04 held
                # a 19.6s and a 25.1s dead stretch, but each sat inside a
                # segment whose other half was real speech -- the ratio came
                # out near 0.5 and passed while the gap went unseen. One
                # segment was redrawn and the two worst were left alone.
                if quiet >= _MIN_VOICED_RATIO and gap <= _MAX_INTERNAL_SILENCE_S:
                    continue
                logger.warning(
                    "Segment is poor against the slide (%.2f voiced, %.1fs gap) -- redrawing: %r",
                    quiet, gap, seg_text[:60],
                )
                redraw_started = time.monotonic()
                redraw_record: dict = {}
                redraw, redraw_sr, ok = _synthesize_segment_with_gate(
                    pipe, seg_text, speaker_audio,
                    max(len(seg_text) / _CHARS_PER_SECOND, 3.0),
                    energy_reference=reference,
                    record=redraw_record,
                )
                _trace(
                    event="redraw", slide=output_path.name, chars=len(seg_text),
                    seconds=round(time.monotonic() - redraw_started, 2),
                    voiced_before=round(quiet, 2), gap_before=round(gap, 1), adopted=ok,
                )
                redraws += 1
                redraw_seconds += time.monotonic() - redraw_started
                if ok:
                    redraws_adopted += 1
                    pieces[idx] = redraw
                    sr = redraw_sr
                    failures = max(0, failures - 1)
                    # This piece's own audio is now the redraw's, generated
                    # fresh with no continuation_ref (see the call above) --
                    # any piece downstream that was generated as a
                    # tts_continuation of the REPLACED audio no longer
                    # reflects what's actually in the joined WAV (F6).
                    metas[leaf_idx]["seed"] = redraw_record.get("seed")
                    metas[leaf_idx]["call"] = redraw_record.get("call")
                    metas[leaf_idx]["fallback"] = False
                    metas[leaf_idx]["continuation_from"] = None
                    adopted_redraw_indices.add(leaf_idx)
            joined = np.concatenate(pieces)

    # F6: flag every piece whose recorded continuation source was one of the
    # pieces actually replaced above. A piece that was itself redrawn now has
    # continuation_from=None (set just above) and drops out of this check.
    boundary_review = sorted(
        i for i, m in enumerate(metas) if m.get("continuation_from") in adopted_redraw_indices
    )

    normalized = _loudness_normalize(joined, sr)
    sf.write(str(output_path), normalized, sr)

    duration = len(normalized) / sr
    reasons = _slide_gate_failures(normalized, sr, len(text), max_seconds)
    # Segment failures are advisory: the per-segment gate picks the best of the
    # seeds, but it cannot decide whether the slide is usable. Its threshold is
    # relative to each segment's own 95th percentile, so a uniformly quiet
    # segment always passes -- it is only quiet compared to its neighbours. That
    # is how slides 018/019/031 shipped with 17-20s of near-inaudible mumbling
    # while every segment reported ok. Only the joined wav can see it.
    if substituted:
        reasons.append(f"{substituted}-silent-substitutions")
    stt_status: str | None = None
    stt_cer: float | None = None
    stt_check: TranscriptionCheck | None = None
    if verify_stt or os.environ.get("RAON_VERIFY_STT") == "1":
        if hasattr(pipe, "stt"):
            stt_check = evaluate_transcription(pipe, output_path, text)
        else:
            # STT was requested but this pipe can't do it (e.g. a fake/mock
            # in tests, or a real pipe built without the STT head) -- record
            # that the check could not run rather than silently skipping it.
            stt_check = TranscriptionCheck(status="unavailable", reasons=[], transcript=None, cer=None)
        reasons.extend(stt_check.reasons)
        stt_status = stt_check.status
        stt_cer = stt_check.cer
    ok = not reasons
    # Spell out the retries. "0 failed gate" only means no segment ended on a
    # fallback; it says nothing about how many draws were spent getting there,
    # and reading it as "no retries" is what hid where the time was going.
    logger.info(
        "Saved slide audio: %s (%.2fs in %.0fs, %d segments, %d ended on fallback, "
        "%d redraws %d adopted costing %.0fs, ok=%s%s)",
        output_path.name, duration, time.monotonic() - slide_started, generated,
        failures, redraws, redraws_adopted, redraw_seconds, ok,
        "" if ok else f", rejected: {','.join(reasons)}",
    )
    _trace(
        event="slide", slide=output_path.name, chars=len(text), segments=generated,
        seconds=round(time.monotonic() - slide_started, 1), duration=round(duration, 1),
        fallbacks=failures, redraws=redraws, redraws_adopted=redraws_adopted,
        redraw_seconds=round(redraw_seconds, 1), ok=ok, rejected=reasons,
        stt_status=stt_status, stt_cer=stt_cer,
    )

    if qc_path is not None:
        segments_qc = [
            SegmentQC(
                index=i,
                text=seg_spans[i][0],
                seed=m.get("seed"),
                call=m.get("call"),
                continuation_from=m.get("continuation_from"),
                fallback=bool(m.get("fallback", False)),
            )
            for i, m in enumerate(metas)
        ]
        _write_slide_qc(
            qc_path, ok=ok, gate_reasons=reasons, stt=stt_check,
            spoken_text=text, segments=segments_qc, boundary_review=boundary_review,
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
