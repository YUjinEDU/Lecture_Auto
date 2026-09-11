"""Tests for lecture_auto.pipeline.raon_tts pure-Python helpers (no GPU/model needed)."""
from __future__ import annotations

import numpy as np

from lecture_auto.pipeline.raon_tts import (
    TTS_SEEDS,
    _integrated_lufs,
    _longest_silence_seconds,
    _loudness_normalize,
    _passes_quality_gate,
    _synthesize_segment_with_gate,
    _trim_lead_tail_silence,
    _voiced_ratio,
    split_into_segments,
)


def test_trim_lead_tail_silence_removes_only_edges():
    sr = 24000
    silence = np.zeros(sr, dtype=np.float32)  # 1s silence
    tone = np.full(sr, 0.5, dtype=np.float32)  # 1s "speech"
    wav = np.concatenate([silence, tone, silence])

    trimmed = _trim_lead_tail_silence(wav, sr)

    # Should be close to the 1s tone (plus small padding), not the original 3s.
    assert sr * 0.9 < len(trimmed) < sr * 1.2
    assert np.abs(trimmed).max() == 0.5


def test_trim_lead_tail_silence_empty_input_is_noop():
    assert _trim_lead_tail_silence(np.array([], dtype=np.float32)).size == 0


def test_trim_lead_tail_silence_all_silence_returns_unchanged():
    wav = np.zeros(1000, dtype=np.float32)
    trimmed = _trim_lead_tail_silence(wav)
    assert len(trimmed) == len(wav)


def _tone(seconds: float, sr: int = 24000, freq: float = 220.0, amp: float = 0.3) -> np.ndarray:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_split_into_segments_never_splits_a_sentence():
    script = "자 오늘은 이것을 배웁니다. 그 다음에 이제 우리가 무엇을 확인해야 하냐면 이겁니다. 마지막 문장이죠?"
    segments = split_into_segments(script, min_chars=10, max_chars=30)
    assert "".join(segments).replace(" ", "") == script.replace(" ", "")
    assert all(len(s) > 0 for s in segments)


def test_split_into_segments_keeps_overlong_sentence_whole():
    long_sentence = "이" * 200 + "다."
    segments = split_into_segments(long_sentence, min_chars=60, max_chars=120)
    assert segments == [long_sentence]


def test_split_into_segments_empty_input():
    assert split_into_segments("") == []


def test_voiced_ratio_all_signal_vs_all_silence():
    sr = 24000
    assert _voiced_ratio(_tone(1.0, sr), sr) == 1.0
    assert _voiced_ratio(np.zeros(sr, dtype=np.float32), sr) == 0.0


def test_longest_silence_seconds_measures_internal_gap():
    sr = 24000
    wav = np.concatenate([_tone(0.5, sr), np.zeros(int(sr * 1.5), dtype=np.float32), _tone(0.5, sr)])
    assert 1.4 < _longest_silence_seconds(wav, sr) < 1.6


def test_passes_quality_gate_rejects_mostly_silent_audio():
    sr = 24000
    # 82% internal silence, matching the observed collapse from single-pass TTS.
    wav = np.concatenate([_tone(0.5, sr), np.zeros(int(sr * 4.0), dtype=np.float32), _tone(0.5, sr)])
    assert not _passes_quality_gate(wav, sr, expected_seconds=1.0)


def test_passes_quality_gate_rejects_runaway_duration():
    sr = 24000
    wav = _tone(10.0, sr)
    assert not _passes_quality_gate(wav, sr, expected_seconds=3.0)


def test_passes_quality_gate_accepts_normal_clip():
    sr = 24000
    wav = _tone(2.0, sr)
    normalized = _loudness_normalize(wav, sr)
    assert _passes_quality_gate(normalized, sr, expected_seconds=2.0)


def test_loudness_normalize_moves_toward_target():
    sr = 24000
    quiet = _tone(2.0, sr, amp=0.02)
    normalized = _loudness_normalize(quiet, sr, target_lufs=-20.0)
    assert _integrated_lufs(normalized, sr) > _integrated_lufs(quiet, sr)


def test_loudness_normalize_silence_is_noop():
    sr = 24000
    silence = np.zeros(sr, dtype=np.float32)
    assert np.array_equal(_loudness_normalize(silence, sr), silence)


class _FakePipe:
    """Minimal stand-in for RaonPipeline.tts() -- returns one waveform per call, in order."""

    def __init__(self, waveforms):
        self.task_params = {"tts": {}, "tts_continuation": {}}
        self._waveforms = list(waveforms)
        self.calls = 0

    def tts(self, text, **kwargs):
        wav = self._waveforms[self.calls]
        self.calls += 1
        return wav.tolist(), 24000  # plain list: no .squeeze/.cpu, exercises the numpy.array() fallback path


def _speech_then_gap(gap_seconds: float, sr: int = 24000) -> np.ndarray:
    """tone - silence - tone, so the gap survives lead/tail trimming as internal silence."""
    tone = _tone(0.3, sr)
    gap = np.zeros(int(sr * gap_seconds), dtype=np.float32)
    return np.concatenate([tone, gap, tone])


def test_synthesize_segment_with_gate_returns_first_passing_seed():
    clean = _tone(3.0, 24000)
    pipe = _FakePipe([clean])  # only one call needed if the first seed passes

    audio, sr, ok = _synthesize_segment_with_gate(pipe, "테스트 문장입니다.", None, expected_seconds=3.0)

    assert ok is True
    assert pipe.calls == 1
    assert len(audio) == len(clean)


def test_synthesize_segment_with_gate_keeps_least_bad_not_first_failure():
    # All three seeds fail (internal gap far exceeds the 2.5s silence limit),
    # but seed 29's gap is the shortest -- the fallback must prefer it over
    # seed 17's, which was tried first.
    waveforms = [
        _speech_then_gap(4.0),  # seed 17
        _speech_then_gap(3.0),  # seed 29 -- least bad
        _speech_then_gap(5.0),  # seed 43
    ]
    pipe = _FakePipe(waveforms)

    audio, sr, ok = _synthesize_segment_with_gate(pipe, "테스트 문장입니다.", None, expected_seconds=3.0)

    assert ok is False
    assert pipe.calls == len(TTS_SEEDS)
    assert len(audio) == len(waveforms[1])
