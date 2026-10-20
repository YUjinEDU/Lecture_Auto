"""Per-segment spectral matching for joined TTS slides.

Raon synthesizes each ~10 s segment independently, so long-term spectral
balance (brightness) jumps at every join: measured on 229 shipped segments the
within-slide spread of spectral tilt was 4.4 dB with adjacent jumps up to
12 dB, while speaker-embedding similarity and median pitch stayed tight. This
nudges each segment's band levels toward the slide median with a capped,
zero-phase EQ before the segments are joined.
"""
from __future__ import annotations

import json
import os
from functools import cache
from itertools import pairwise
from pathlib import Path

import numpy as np

VOICE_MATCH_ENV = "LECTURE_AUTO_VOICE_MATCH"
VOICE_TARGET_ENV = "LECTURE_AUTO_VOICE_TARGET"
VOICE_TARGET_PATH = Path(__file__).resolve().parents[2] / "config" / "voice_target.json"
MAX_GAIN_DB = 3.5
MIN_SEGMENTS = 3

_N_FFT = 1024
_HOP = 512
_EDGES = 100.0 * 2.0 ** (np.arange(0, 21) / 3.0)
_EDGES = _EDGES[_EDGES < 10000.0]
BAND_CENTERS_HZ = np.sqrt(_EDGES[:-1] * _EDGES[1:])


def voice_match_enabled() -> bool:
    return os.environ.get(VOICE_MATCH_ENV, "0") == "1"


def band_levels_db(x: np.ndarray, sr: int) -> np.ndarray | None:
    """Mean power in 1/3-octave bands over the louder 60% of frames; None if unusable."""
    if len(x) < 2 * _N_FFT or not np.any(x):
        return None
    n_frames = (len(x) - _N_FFT) // _HOP
    idx = np.arange(_N_FFT)[None, :] + _HOP * np.arange(n_frames)[:, None]
    frames = x[idx].astype(np.float64) * np.hanning(_N_FFT)
    energy = (frames ** 2).mean(axis=1)
    loud = frames[energy > np.percentile(energy, 40)]
    if len(loud) == 0:
        return None
    power = (np.abs(np.fft.rfft(loud, axis=1)) ** 2).mean(axis=0)
    freqs = np.fft.rfftfreq(_N_FFT, 1.0 / sr)
    levels = np.array([
        10.0 * np.log10(power[(freqs >= lo) & (freqs < hi)].mean() + 1e-20)
        for lo, hi in pairwise(_EDGES)
    ])
    return levels if np.all(np.isfinite(levels)) else None


def split_speech_segments(wav: np.ndarray, sr: int, min_pause_s: float = 0.15, min_len_s: float = 1.5) -> list[tuple[int, int]]:
    """(start, end) sample spans of the pieces a slide WAV was joined from.

    The joiner inserts exactly-zero pauses, so those runs are the boundaries.
    """
    zero = np.concatenate(([False], np.abs(wav) < 1e-9, [False]))
    edges = np.diff(zero.astype(np.int8))
    spans, start = [], 0
    for a, b in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        if (b - a) / sr >= min_pause_s:
            if (a - start) / sr >= min_len_s:
                spans.append((start, int(a)))
            start = int(b)
    if (len(wav) - start) / sr >= min_len_s:
        spans.append((start, len(wav)))
    return spans


def _smooth(values: np.ndarray) -> np.ndarray:
    padded = np.pad(values, 1, mode="edge")
    return np.convolve(padded, np.ones(3) / 3.0, mode="valid")


def _apply_gain(x: np.ndarray, sr: int, gain_db: np.ndarray) -> np.ndarray:
    samples = x.astype(np.float64)
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(len(samples), 1.0 / sr)
    curve = np.interp(np.log(np.maximum(freqs, 1.0)), np.log(BAND_CENTERS_HZ), gain_db)
    filtered = np.fft.irfft(spectrum * 10.0 ** (curve / 20.0), n=len(samples))
    rms_in = np.sqrt(np.mean(samples ** 2))
    rms_out = np.sqrt(np.mean(filtered ** 2))
    return (filtered * (rms_in / rms_out)).astype(np.float32)


@cache
def _read_target(path: str) -> np.ndarray | None:
    file = Path(path)
    if not file.exists():
        return None
    profile = np.asarray(json.loads(file.read_text(encoding="utf-8"))["profile_db"], dtype=float)
    return profile if profile.shape == BAND_CENTERS_HZ.shape else None


def load_voice_target(path: Path = VOICE_TARGET_PATH) -> np.ndarray | None:
    """The fixed level-independent profile, or None to match against the slide's own median.

    ``LECTURE_AUTO_VOICE_TARGET=slide`` forces the per-slide behaviour.
    """
    if os.environ.get(VOICE_TARGET_ENV) == "slide":
        return None
    return _read_target(str(path))


def match_segment_spectra(
    segments: list[np.ndarray], sr: int, target: np.ndarray | None = None
) -> list[np.ndarray]:
    """Return segments with band levels pulled toward a target (RMS preserved).

    With a fixed ``target`` (mean-removed profile) every measurable segment is
    corrected, so slides agree with each other and one-segment slides are covered.
    Without one, the goal is the slide's median, which needs ``MIN_SEGMENTS``
    measurable segments: a median of one or two is just another segment.
    Segments too short or silent to measure pass through untouched.
    """
    levels = [band_levels_db(s, sr) for s in segments]
    measurable = [lv for lv in levels if lv is not None]
    if target is None and len(measurable) < MIN_SEGMENTS:
        return list(segments)
    goal = target if target is not None else np.median(np.stack(measurable), axis=0)
    matched = []
    for segment, level in zip(segments, levels):
        if level is None:
            matched.append(segment)
            continue
        current = level - level.mean() if target is not None else level
        gain = _smooth(np.clip(goal - current, -MAX_GAIN_DB, MAX_GAIN_DB))
        matched.append(_apply_gain(segment, sr, gain))
    return matched
