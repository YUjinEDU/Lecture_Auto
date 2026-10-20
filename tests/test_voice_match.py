"""Tests for lecture_auto.pipeline.voice_match (pure numpy, no GPU/model)."""
from __future__ import annotations

import json

import numpy as np
import pytest
from scipy.signal import butter, sosfilt

from lecture_auto.pipeline import raon_tts
from lecture_auto.pipeline.voice_match import (
    BAND_CENTERS_HZ,
    MAX_GAIN_DB,
    VOICE_MATCH_ENV,
    VOICE_TARGET_ENV,
    _read_target,
    band_levels_db,
    load_voice_target,
    match_segment_spectra,
    split_speech_segments,
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

    def spy(segments, sr, target=None):
        seen.append(len(segments))
        return real(segments, sr, target)

    monkeypatch.setattr(raon_tts, "match_segment_spectra", spy)
    monkeypatch.setenv(VOICE_MATCH_ENV, flag)

    raon_tts.synthesize_raon_slide(_NoisePipe(), " ".join(_SENTENCES), tmp_path / "slide.wav", max_seconds=60.0)

    assert len(seen) == expected_calls
    if expected_calls:
        assert seen == [3]


def _profile(x):
    levels = band_levels_db(x, SR)
    return levels - levels.mean()


def test_fixed_target_corrects_a_single_segment_that_slide_median_leaves_alone():
    target = _profile(_noise(0, 4000))
    dark = _noise(1, 2500)

    assert np.array_equal(match_segment_spectra([dark], SR)[0], dark)
    [matched] = match_segment_spectra([dark], SR, target)

    assert np.abs(_profile(matched) - target).mean() < np.abs(_profile(dark) - target).mean() * 0.8
    assert _rms(matched) == pytest.approx(_rms(dark), rel=0.02)


def test_fixed_target_pulls_segments_of_different_slides_toward_each_other():
    target = _profile(_noise(0, 4000))
    slide_a, slide_b = _noise(1, 2500), _noise(2, 6000)

    matched = match_segment_spectra([slide_a], SR, target) + match_segment_spectra([slide_b], SR, target)

    assert np.abs(_profile(matched[0]) - _profile(matched[1])).mean() < np.abs(_profile(slide_a) - _profile(slide_b)).mean() * 0.8


def test_load_voice_target_reads_the_file_and_honours_the_slide_switch(tmp_path, monkeypatch):
    good = tmp_path / "t.json"
    good.write_text(json.dumps({"profile_db": [0.5] * len(BAND_CENTERS_HZ)}), encoding="utf-8")
    wrong = tmp_path / "w.json"
    wrong.write_text(json.dumps({"profile_db": [0.0, 1.0]}), encoding="utf-8")
    _read_target.cache_clear()
    monkeypatch.delenv(VOICE_TARGET_ENV, raising=False)

    assert load_voice_target(good).tolist() == [0.5] * len(BAND_CENTERS_HZ)
    assert load_voice_target(wrong) is None
    assert load_voice_target(tmp_path / "missing.json") is None

    monkeypatch.setenv(VOICE_TARGET_ENV, "slide")
    assert load_voice_target(good) is None


def test_committed_voice_target_matches_the_band_layout():
    _read_target.cache_clear()
    target = load_voice_target()

    assert target is not None and target.shape == BAND_CENTERS_HZ.shape
    assert abs(float(target.mean())) < 0.05


def test_split_speech_segments_follows_the_zero_pauses():
    tone = _noise(0, 3000, seconds=2.0)
    wav = np.concatenate([tone, np.zeros(int(SR * 0.2), dtype=np.float32), tone, np.zeros(int(SR * 0.2), dtype=np.float32), tone])

    spans = split_speech_segments(wav, SR)

    assert len(spans) == 3
    assert all(abs((b - a) / SR - 2.0) < 0.01 for a, b in spans)
