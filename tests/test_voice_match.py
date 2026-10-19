"""Tests for lecture_auto.pipeline.voice_match (pure numpy, no GPU/model)."""
from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import butter, sosfilt

from lecture_auto.pipeline import raon_tts
from lecture_auto.pipeline.voice_match import (
    MAX_GAIN_DB,
    VOICE_MATCH_ENV,
    band_levels_db,
    match_segment_spectra,
    voice_match_enabled,
)

SR = 24000


def _noise(seed: int, cutoff_hz: float, seconds: float = 8.0, rms: float = 0.1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    x = sosfilt(butter(2, cutoff_hz, fs=SR, output="sos"), rng.standard_normal(int(SR * seconds)))
    return (x * rms / np.sqrt(np.mean(x ** 2))).astype(np.float32)


def _dispersion(segments: list[np.ndarray]) -> float:
    levels = np.stack([band_levels_db(s, SR) for s in segments])
    return float(levels.std(axis=0).mean())


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))


def test_matching_reduces_spectral_dispersion_and_preserves_level():
    segments = [_noise(i, cutoff) for i, cutoff in enumerate([3000, 4200, 3400, 5000, 3200])]

    matched = match_segment_spectra(segments, SR)

    assert _dispersion(matched) < _dispersion(segments) * 0.9
    for before, after in zip(segments, matched):
        assert len(after) == len(before)
        assert np.all(np.isfinite(after))
        assert np.abs(after).max() < 1.0
        assert _rms(after) == pytest.approx(_rms(before), rel=0.02)


def test_fewer_than_three_measurable_segments_are_unchanged():
    segments = [_noise(0, 3000), _noise(1, 5000), np.zeros(SR, dtype=np.float32)]

    matched = match_segment_spectra(segments, SR)

    assert all(np.array_equal(a, b) for a, b in zip(segments, matched))


def test_silent_and_too_short_segments_pass_through_untouched():
    silent = np.zeros(SR, dtype=np.float32)
    short = _noise(9, 3000, seconds=0.05)
    segments = [_noise(0, 3000), _noise(1, 5000), silent, _noise(2, 3600), short, _noise(3, 4200)]

    matched = match_segment_spectra(segments, SR)

    assert np.array_equal(matched[2], silent)
    assert np.array_equal(matched[4], short)
    assert not np.array_equal(matched[1], segments[1])


def test_spectral_reshaping_is_capped_and_extreme_segments_are_not_flattened():
    dark = _noise(0, 300)
    segments = [dark, _noise(1, 4000), _noise(2, 4200), _noise(3, 3800)]

    matched = match_segment_spectra(segments, SR)

    change = band_levels_db(matched[0], SR) - band_levels_db(dark, SR)
    assert np.ptp(change) <= 2 * MAX_GAIN_DB + 1.0
    brightest_band_after = band_levels_db(matched[0], SR)[-1]
    assert brightest_band_after < min(band_levels_db(m, SR)[-1] for m in matched[1:]) - 10.0


def test_enabled_only_by_env_flag(monkeypatch):
    monkeypatch.delenv(VOICE_MATCH_ENV, raising=False)
    assert voice_match_enabled() is False

    monkeypatch.setenv(VOICE_MATCH_ENV, "0")
    assert voice_match_enabled() is False

    monkeypatch.setenv(VOICE_MATCH_ENV, "1")
    assert voice_match_enabled() is True


_SENTENCES = [
    "첫 번째 문장을 아주 충분히 길게 만들어서 확실하게 하나의 독립된 조각이 되도록 열심히 작성하는 문장입니다.",
    "두 번째 문장도 마찬가지로 아주 충분히 길게 만들어서 확실하게 별도의 조각이 되도록 열심히 작성하는 문장입니다.",
    "세 번째 문장 역시 아주 충분히 길게 만들어서 확실하게 따로 떨어진 조각이 되도록 열심히 작성하는 문장입니다.",
]


class _NoisePipe:
    def __init__(self):
        self.task_params = {"tts": {}}
        self._cutoffs = iter([3000, 5000, 3400] * 4)

    def tts(self, text, **kwargs):
        return _noise(len(text), next(self._cutoffs), seconds=10.0).tolist(), SR


@pytest.mark.parametrize("flag, expected_calls", [("1", 1), ("0", 0)])
def test_synthesize_raon_slide_matches_segments_only_when_enabled(
    monkeypatch, tmp_path, flag, expected_calls
):
    seen: list[int] = []
    real = raon_tts.match_segment_spectra

    def spy(segments, sr):
        seen.append(len(segments))
        return real(segments, sr)

    monkeypatch.setattr(raon_tts, "match_segment_spectra", spy)
    monkeypatch.setenv(VOICE_MATCH_ENV, flag)

    raon_tts.synthesize_raon_slide(_NoisePipe(), " ".join(_SENTENCES), tmp_path / "slide.wav", max_seconds=60.0)

    assert len(seen) == expected_calls
    if expected_calls:
        assert seen == [3]
