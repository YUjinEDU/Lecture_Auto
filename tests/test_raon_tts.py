"""Tests for lecture_auto.pipeline.raon_tts pure-Python helpers (no GPU/model needed)."""
from __future__ import annotations

import numpy as np
import soundfile as sf

from lecture_auto.pipeline.raon_tts import (
    _MAX_INTERNAL_SILENCE_S,
    _MIN_VOICED_RATIO,
    TTS_SEEDS,
    _integrated_lufs,
    _longest_silence_seconds,
    _loudness_normalize,
    _passes_quality_gate,
    _slide_gate_failures,
    _speech_reference,
    _synthesize_segment_with_gate,
    _trim_lead_tail_silence,
    _voiced_ratio,
    plan_attempts,
    split_in_half,
    split_into_segments,
    synthesize_raon_slide,
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
        if wav is None:
            raise TypeError("'NoneType' object is not subscriptable")  # mirrors modeling_raon.py's real failure
        return wav.tolist(), 24000  # plain list: no .squeeze/.cpu, exercises the numpy.array() fallback path

    def tts_continuation(self, target_text, ref_audio, ref_text, **kwargs):
        # Segments after the first go through this, not tts(). Without it the
        # fake raises AttributeError, every seed is swallowed by the retry
        # handler, and a "clean audio" test would silently exercise only the
        # all-seeds-failed path.
        return self.tts(target_text)


def _speech_then_gap(gap_seconds: float, sr: int = 24000) -> np.ndarray:
    """tone - silence - tone, so the gap survives lead/tail trimming as internal silence."""
    tone = _tone(0.3, sr)
    gap = np.zeros(int(sr * gap_seconds), dtype=np.float32)
    return np.concatenate([tone, gap, tone])


def test_synthesize_segment_with_gate_returns_first_passing_seed():
    clean = _tone(3.0, 24000)
    pipe = _FakePipe([clean])  # only one call needed if the first seed passes

    audio, _sr, ok = _synthesize_segment_with_gate(pipe, "테스트 문장입니다.", None, expected_seconds=3.0)

    assert ok is True
    assert pipe.calls == 1
    assert len(audio) == len(clean)


def test_synthesize_segment_with_gate_keeps_least_bad_not_first_failure():
    # Every seed fails (internal gap far exceeds the 2.5s silence limit), but
    # the second one's gap is the shortest -- the fallback must prefer it over
    # the first, which was tried first. Sized off TTS_SEEDS so adding a seed
    # does not silently turn this into an index error.
    waveforms = [_speech_then_gap(4.0), _speech_then_gap(3.0)] + [
        _speech_then_gap(5.0) for _ in range(len(plan_attempts(has_continuation=False)) - 2)
    ]
    pipe = _FakePipe(waveforms)

    audio, _sr, ok = _synthesize_segment_with_gate(pipe, "테스트 문장입니다.", None, expected_seconds=3.0)

    assert ok is False
    assert pipe.calls == len(plan_attempts(has_continuation=False))
    assert len(audio) == len(waveforms[1])


def test_synthesize_segment_with_gate_survives_a_raising_seed():
    # seed 17 raises (the modeling_raon.py 'audio[0] on None' bug that killed
    # a real batch run), seed 29 produces clean audio -- must not propagate
    # the exception, must return the working seed's result.
    waveforms = [None, _tone(3.0, 24000)]
    pipe = _FakePipe(waveforms)

    audio, _sr, ok = _synthesize_segment_with_gate(pipe, "테스트 문장입니다.", None, expected_seconds=3.0)

    assert ok is True
    assert pipe.calls == 2
    assert len(audio) == len(waveforms[1])


def test_synthesize_segment_with_gate_all_seeds_raising_degrades_to_silence():
    pipe = _FakePipe([None] * len(plan_attempts(has_continuation=False)))

    audio, sr, ok = _synthesize_segment_with_gate(pipe, "테스트 문장입니다.", None, expected_seconds=3.0)

    assert ok is False
    assert pipe.calls == len(plan_attempts(has_continuation=False))
    assert np.all(audio == 0.0)
    assert len(audio) == int(sr * 3.0)


# ---------------------------------------------------------------------------
# Lower duration bound: a generation that stops early has no long silence and
# a healthy voiced ratio, so nothing but a floor catches the lost narration.
# ---------------------------------------------------------------------------

def test_passes_quality_gate_rejects_truncated_clip():
    sr = 24000
    # 27s of clean speech where ~42s was expected -- the real slide_009 failure.
    truncated = _tone(26.9, sr)
    assert _passes_quality_gate(truncated, sr, expected_seconds=41.6) is True
    assert _passes_quality_gate(truncated, sr, expected_seconds=41.6, min_seconds=33.3) is False


def test_passes_quality_gate_accepts_clip_at_the_floor():
    sr = 24000
    assert _passes_quality_gate(_tone(34.0, sr), sr, expected_seconds=41.6, min_seconds=33.3) is True


# ---------------------------------------------------------------------------
# split_in_half: the escape hatch that makes a retry produce different audio.
# ---------------------------------------------------------------------------

def test_split_in_half_prefers_sentence_boundary_nearest_the_middle():
    text = "첫 번째 문장은 이렇게 시작합니다. 두 번째 문장이 이어집니다. 세 번째 문장으로 마무리합니다."
    halves = split_in_half(text)
    assert len(halves) == 2
    # 19/33 chars beats 38/18 -- the join point closest to the midpoint wins.
    assert halves[0] == "첫 번째 문장은 이렇게 시작합니다."
    assert halves[1].startswith("두 번째") and halves[1].endswith("마무리합니다.")


def test_split_in_half_falls_back_to_clause_boundary_for_one_sentence():
    text = "이 문장은 마침표가 하나뿐이지만 중간에 쉼표가 있고, 그 뒤로도 설명이 계속 이어지는 긴 문장입니다."
    halves = split_in_half(text)
    assert len(halves) == 2
    assert all(len(h) >= 15 for h in halves)


def test_split_in_half_returns_unsplittable_text_unchanged():
    assert split_in_half("짧은 문장.") == ["짧은 문장."]


def test_split_in_half_never_loses_characters():
    text = "하나입니다. 둘입니다. 셋입니다. 넷입니다."
    halves = split_in_half(text)
    assert "".join(halves).replace(" ", "") == text.replace(" ", "")


# ---------------------------------------------------------------------------
# Failure must reach the caller: a cached gate failure is the bug that shipped
# 29 bad wavs into lecture 01.
# ---------------------------------------------------------------------------

def test_synthesize_slide_reports_failure_when_segments_cannot_be_saved(tmp_path):
    # Every call returns audio with a 6s internal gap -> fails the silence gate
    # at every seed and every split depth.
    bad = _speech_then_gap(6.0)
    pipe = _FakePipe([bad] * 200)
    out = tmp_path / "slide.wav"
    path, ok = synthesize_raon_slide(pipe, "첫 문장입니다. 두 번째 문장입니다.", out)
    assert path.exists()
    assert ok is False


def test_synthesize_slide_reports_success_on_clean_audio(tmp_path):
    pipe = _FakePipe([_tone(5.0)] * 50)
    out = tmp_path / "slide.wav"
    _, ok = synthesize_raon_slide(pipe, "첫 문장입니다.", out)
    assert ok is True


def test_synthesize_slide_fails_when_joined_audio_blows_its_budget(tmp_path):
    # Each segment passes its own gate, but they sum past max_seconds * 1.8 --
    # the whole-slide check review item 2 asked for.
    pipe = _FakePipe([_tone(5.0)] * 50)
    out = tmp_path / "slide.wav"
    _, ok = synthesize_raon_slide(
        pipe, "첫 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다.", out, max_seconds=2.0
    )
    assert ok is False


def test_synthesize_slide_splits_and_retries_a_failing_segment(tmp_path):
    # Every draw of the whole segment fails the silence gate, and seeding is
    # deterministic, so exceeding one round of draws is what proves the split
    # path ran. The text is sized past _MIN_SPLIT_WORTH_CHARS on purpose: below
    # that a split only yields fragments the gate reads least reliably, and
    # test_short_segments_are_not_split_further pins that side of the rule.
    attempts = len(plan_attempts(has_continuation=False))
    waveforms = [_speech_then_gap(6.0)] * attempts + [_tone(4.0)] * 50
    pipe = _FakePipe(waveforms)
    out = tmp_path / "slide.wav"
    synthesize_raon_slide(
        pipe,
        "첫 번째 문장은 이렇게 길게 시작해서 충분한 분량을 확보합니다. "
        "두 번째 문장도 마찬가지로 넉넉한 길이를 갖도록 이어서 작성합니다.",
        out,
    )
    assert pipe.calls > attempts


def test_quiet_segment_passes_alone_but_sinks_the_slide(tmp_path):
    """The v8 regression: slides 018/019/031 shipped with ~20s of mumbling.

    Each segment's gate measures energy against that segment's OWN 95th
    percentile, so a uniformly quiet generation looks perfectly voiced to
    itself and reports ok. Only against the slide's real speech does it read
    as the silence a listener hears. The slide gate has to catch what every
    segment gate missed.
    """
    sr = 24000
    loud = _tone(6.0, sr, amp=0.3)
    quiet = _tone(6.0, sr, amp=0.01)  # 30x quieter: audible alone, silence in context

    # Alone, the quiet clip is fully voiced -- this is the blind spot itself.
    assert _voiced_ratio(quiet, sr) == 1.0
    assert _passes_quality_gate(quiet, sr, expected_seconds=6.0)

    # Joined with real speech, it is silence, and the slide gate says so.
    joined = np.concatenate([loud, quiet, loud])
    reasons = _slide_gate_failures(joined, sr, char_count=int(18 * 5.7), max_seconds=20.0)
    assert any(r.startswith("silence") for r in reasons), reasons


def test_slide_gate_accepts_ordinary_speech():
    sr = 24000
    wav = np.concatenate([_tone(10.0, sr), np.zeros(int(sr * 1.0), dtype=np.float32), _tone(10.0, sr)])
    assert _slide_gate_failures(wav, sr, char_count=int(21 * 5.7), max_seconds=25.0) == []


def test_slide_gate_flags_truncation_and_overrun():
    sr = 24000
    short = _tone(5.0, sr)
    assert any(r.startswith("short") for r in _slide_gate_failures(short, sr, int(30 * 5.7), 30.0))
    long = _tone(70.0, sr)
    assert any(r.startswith("long") for r in _slide_gate_failures(long, sr, int(70 * 5.7), 30.0))


def test_marginal_segment_does_not_sink_an_otherwise_good_slide(tmp_path):
    """Slides 010/002: joined audio clean, rejected because one segment was marginal.

    The segment gate exists to rank seeds, not to judge the artifact. Only the
    joined wav decides -- otherwise a slide a listener would accept is thrown
    away for a defect that concatenation already absorbed.
    """
    sr = 24000
    # Second segment is short enough to fail its own duration floor, but the
    # joined slide is continuous speech with no long gap.
    pipe = _FakePipe([_tone(8.0, sr), _tone(0.4, sr), _tone(8.0, sr)] * len(TTS_SEEDS) * 4)
    out = tmp_path / "slide.wav"
    _, ok = synthesize_raon_slide(
        pipe, "첫 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다.", out, max_seconds=30.0
    )
    wav, got_sr = sf.read(str(out))
    assert _slide_gate_failures(wav, got_sr, char_count=len("첫 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다."), max_seconds=30.0) == []
    assert ok, "joined audio passes every check; a marginal segment must not veto it"


def test_silence_substitution_always_fails_the_slide(tmp_path):
    """All seeds raising drops a sentence outright -- never cacheable."""
    pipe = _FakePipe([None] * len(TTS_SEEDS) * 8)
    out = tmp_path / "slide.wav"
    _, ok = synthesize_raon_slide(pipe, "한 문장짜리 짧은 대사입니다.", out, max_seconds=30.0)
    assert not ok


def test_quiet_segment_is_redrawn_against_the_slide_level(tmp_path):
    """The 018/019/038 root cause: a quiet segment never consumed a retry.

    Judged against itself it is fully voiced, so its gate passed, so no seed
    after the first was ever tried -- adding seeds changed nothing and the
    slide came back byte-identical. The second pass re-judges it against the
    slide's real speech and redraws it.
    """
    sr = 24000
    loud, quiet = _tone(9.0, sr, amp=0.3), _tone(9.0, sr, amp=0.005)
    # First pass: segment 2 comes out quiet. Redraw returns a loud take.
    pipe = _FakePipe([loud, quiet, loud] + [loud] * 12)
    out = tmp_path / "slide.wav"
    text = "첫 번째 문장입니다. " * 3 + "두 번째 문장입니다. " * 3 + "세 번째 문장입니다. " * 3
    synthesize_raon_slide(pipe, text, out, max_seconds=90.0)

    wav, got_sr = sf.read(str(out))
    ref = _speech_reference(wav, got_sr)
    assert _voiced_ratio(wav, got_sr, reference=ref) >= _MIN_VOICED_RATIO
    assert pipe.calls > 3, "the quiet segment must have been redrawn, not accepted"


def test_speech_reference_makes_a_quiet_clip_read_as_silence():
    sr = 24000
    loud, quiet = _tone(5.0, sr, amp=0.3), _tone(5.0, sr, amp=0.005)
    assert _voiced_ratio(quiet, sr) == 1.0  # judged against itself
    ref = _speech_reference(np.concatenate([loud, quiet]), sr)
    assert _voiced_ratio(quiet, sr, reference=ref) == 0.0  # judged against real speech


def test_continuation_gives_up_after_two_seeds_and_falls_back_to_plain_tts():
    """tts_continuation fails identically on every seed; plain tts never has.

    Spending all the draws on continuation was the most expensive thing this
    module did. Two, then switch.
    """
    attempts = plan_attempts(has_continuation=True)
    assert [use for _, use in attempts] == [True, True, False, False]
    assert len(attempts) < len(TTS_SEEDS) + 2  # strictly cheaper than every seed twice


def test_short_segments_are_not_split_further(tmp_path):
    """A failing short segment is reported, not recursively redrawn.

    Each split level multiplies generations, and the fragments it produces are
    the ones the gate judges least reliably.
    """
    sr = 24000
    bad = _speech_then_gap(6.0, sr)   # fails the gate however often it is drawn
    pipe = _FakePipe([bad] * 64)
    out = tmp_path / "slide.wav"
    synthesize_raon_slide(pipe, "짧은 문장 하나입니다.", out, max_seconds=10.0)
    # One segment, one round of draws, no split: bounded by the attempt plan.
    assert pipe.calls <= len(plan_attempts(has_continuation=False))


def test_dead_stretch_inside_a_half_good_segment_is_redrawn():
    """Slide 018 of lecture 04: one redraw fired, the two worst gaps were missed.

    A segment that is half real speech and half dead air scores about 0.5
    voiced -- over the threshold -- so the ratio alone never saw it. The gap is
    what gives it away.
    """
    sr = 24000
    half_good = np.concatenate([_tone(20.0, sr, amp=0.3), _tone(20.0, sr, amp=0.004)])
    reference = _speech_reference(half_good, sr)

    assert _voiced_ratio(half_good, sr, reference=reference) >= _MIN_VOICED_RATIO
    assert _longest_silence_seconds(half_good, sr, reference=reference) > _MAX_INTERNAL_SILENCE_S
