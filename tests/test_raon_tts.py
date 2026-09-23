"""Tests for lecture_auto.pipeline.raon_tts pure-Python helpers (no GPU/model needed)."""
from __future__ import annotations

import hashlib

import numpy as np
import soundfile as sf

from lecture_auto.pipeline.raon_tts import (
    _MAX_INTERNAL_SILENCE_S,
    _MIN_VOICED_RATIO,
    TTS_SEEDS,
    TranscriptionCheck,
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


def test_split_children_carry_their_own_text_not_the_parents():
    """A redraw after a split must re-speak the half, never the whole segment.

    _synthesize_with_splitting used to return audio without text, so the caller
    labelled both halves with the parent. Redrawing the first half then
    synthesized the parent into the first half's slot and the slide said the
    second half twice.
    """
    import tempfile
    from pathlib import Path as _Path

    from lecture_auto.pipeline.raon_tts import _SplitState, _synthesize_with_splitting

    sr = 24000
    attempts = len(plan_attempts(has_continuation=False))
    parent = "첫 번째 문장은 이렇게 길게 시작해서 충분한 분량을 확보합니다. 두 번째 문장도 마찬가지로 넉넉한 길이를 갖도록 이어서 작성합니다."
    # Whole segment fails every draw, then both halves come back clean.
    # 7s clears the halves' own duration floor (35 chars / 5.7 * 0.7 = 4.3s).
    pipe = _FakePipe([_speech_then_gap(6.0, sr)] * attempts + [_tone(7.0, sr)] * 40)

    with tempfile.TemporaryDirectory() as tmp:
        pieces, ok, _ = _synthesize_with_splitting(
            pipe, parent, None, None, depth=0, state=_SplitState(_Path(tmp))
        )

    assert ok, "both halves are clean, so the split should have been accepted"
    assert len(pieces) == 2, f"expected the two halves, got {len(pieces)}"
    texts = [t for t, _, _ in pieces]
    assert all(t != parent for t in texts), "a half is labelled with the whole parent text"
    assert "".join(texts).replace(" ", "") == parent.replace(" ", "")


def test_trace_records_every_attempt_and_redraw(tmp_path, monkeypatch):
    """The summary line hid retries: '0 failed gate' says nothing about cost.

    Tracing has to show each draw that was spent, not just where the segment
    landed, and has to say whether a redraw was actually adopted.
    """
    import importlib
    import json as _json

    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("RAON_TRACE", str(trace))
    mod = importlib.reload(importlib.import_module("lecture_auto.pipeline.raon_tts"))
    try:
        sr = 24000
        pipe = _FakePipe([_speech_then_gap(6.0, sr)] * 2 + [_tone(7.0, sr)] * 40)
        mod._synthesize_segment_with_gate(pipe, "짧은 문장 하나입니다.", None, expected_seconds=5.0)

        rows = [_json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines()]
        assert len(rows) >= 2, "each draw must be recorded, not just the last"
        assert [r["outcome"] for r in rows][:2] == ["gate_fail", "gate_fail"]
        assert all("max_new_tokens" in r and "seconds" in r for r in rows)
        # No invented token counts: the pipeline returns a waveform, not usage.
        assert all("tokens_generated" not in r for r in rows)
    finally:
        monkeypatch.delenv("RAON_TRACE", raising=False)
        importlib.reload(mod)


def test_trace_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("RAON_TRACE", raising=False)
    import importlib
    mod = importlib.reload(importlib.import_module("lecture_auto.pipeline.raon_tts"))
    assert mod._TRACE_PATH is None
    mod._trace(event="attempt")  # must be a no-op, not an error


def test_split_into_segments_sweetspot_behavior():
    # Slide 23 text: 187 chars should cleanly split into two sweetspot segments (85 and 101 chars)
    # instead of the old 120 + 66 char split.
    text = (
        "그래서 포스트잇이 충분히 모이면 우리가 공통적인 속성을 기준으로 묶어봅니다. "
        "비슷한 내용끼리 모으고, 그 묶음의 특징을 잘 보여주는 제목을 붙이는 거죠. "
        "중요한 건 보기 좋게 정리하는 데서 끝나지 않는다는 점입니다. "
        "서로 떨어져 있던 내용이 연결되면서 새로운 관점이나 인사이트가 보이면, "
        "그것도 별도의 포스트잇에 바로 적어두는 겁니다."
    )
    segments = split_into_segments(text)
    assert len(segments) == 2
    assert 75 <= len(segments[0]) <= 105
    assert 75 <= len(segments[1]) <= 105


def test_split_into_segments_splits_overlong_sentence_at_clause_boundary():
    # A single sentence of ~130 chars without period, but with clauses.
    long_sent = (
        "디자인씽킹은 현장에서 문제를 겪고 있는 실제 사용자의 고통과 숨겨진 요구사항을 깊이 있게 공감하고, "
        "이를 바탕으로 문제를 새롭게 정의하며 창의적인 해결 아이디어를 도출하여 프로토타입으로 검증하는 실천적 방법론입니다."
    )
    assert len(long_sent) > 105
    segments = split_into_segments(long_sent)
    assert len(segments) >= 2
    assert all(len(s) <= 105 for s in segments)
    assert "".join(segments).replace(" ", "") == long_sent.replace(" ", "")


def test_slide_gate_catches_moderate_truncation_under_78_percent():
    sr = 24000
    # Expected 40s (approx 228 chars), but audio is 30s (0.75x ratio).
    # Old 0.70 threshold let this slip through (the slide 041 defect), 0.78 must catch it.
    char_count = int(40 * 5.7)
    clip_30s = _tone(30.0, sr)
    failures = _slide_gate_failures(clip_30s, sr, char_count=char_count, max_seconds=40.0)
    assert any(f.startswith("short") for f in failures), failures


def test_slide_gate_catches_internal_silence_over_2_8s():
    sr = 24000
    # 3.0s internal silence (like slide 023's 3.8s). Old 3.5s limit missed 3.0s, new 2.8s catches it.
    clip = np.concatenate([_tone(5.0, sr), np.zeros(int(sr * 3.0), dtype=np.float32), _tone(5.0, sr)])
    failures = _slide_gate_failures(clip, sr, char_count=int(13 * 5.7), max_seconds=20.0)
    assert any(f.startswith("silence") for f in failures), failures


def test_slide_gate_catches_duration_overrun_over_1_35():
    sr = 24000
    # max_seconds = 20s. Output is 28s (1.40x).
    # Old 1.80 limit allowed up to 36s (causing babble/stretching), 1.35 catches 28s.
    clip_28s = _tone(28.0, sr)
    failures = _slide_gate_failures(clip_28s, sr, char_count=int(20 * 5.7), max_seconds=20.0)
    assert any(f.startswith("long") for f in failures), failures


def test_check_transcription_fidelity_catches_repetition_and_discrepancy(tmp_path):
    from unittest.mock import MagicMock

    from lecture_auto.pipeline.raon_tts import check_transcription_fidelity

    fake_pipe = MagicMock()
    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    # 1. Word repetition: "그렇죠 그렇죠 그렇죠"
    fake_pipe.stt.return_value = "우리가 문제를 해결해야 하는데 그렇죠 그렇죠 그렇죠 계속해서 진행합니다."
    reasons = check_transcription_fidelity(fake_pipe, audio_path, "우리가 문제를 해결해야 합니다.")
    assert any("stt_repetition" in r for r in reasons)

    # 2. Phrase loop: "우리가 배운 우리가 배운"
    fake_pipe.stt.return_value = "이것은 우리가 배운 우리가 배운 핵심 개념입니다."
    reasons = check_transcription_fidelity(fake_pipe, audio_path, "이것은 우리가 배운 핵심 개념입니다.")
    assert any("stt_phrase_loop" in r for r in reasons)

    # 3. Short discrepancy (dropped half text)
    fake_pipe.stt.return_value = "앞부분만 조금 읽고 멈춤"
    reasons = check_transcription_fidelity(fake_pipe, audio_path, "이 문장은 전체적으로 아주 길게 작성된 스크립트로서 끝까지 다 읽어야 합니다.")
    assert any("stt_short" in r for r in reasons)

    # 4. Clean fidelity
    script = "자 다음으로 보실 내용은 디자인씽킹의 핵심 원리입니다."
    fake_pipe.stt.return_value = "자 다음으로 보실 내용은 디자인씽킹의 핵심 원리입니다."
    assert check_transcription_fidelity(fake_pipe, audio_path, script) == []


def test_evaluate_transcription_stt_exception_is_unavailable(tmp_path):
    from unittest.mock import MagicMock

    from lecture_auto.pipeline.raon_tts import (
        check_transcription_fidelity,
        evaluate_transcription,
    )

    fake_pipe = MagicMock()
    fake_pipe.stt.side_effect = RuntimeError("stt boom")
    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    check = evaluate_transcription(fake_pipe, audio_path, "아무 문장입니다.")
    assert check.status == "unavailable"
    assert check.reasons == []
    assert check.transcript is None
    assert check.cer is None
    # Existing gate semantics unchanged: exception -> [].
    assert check_transcription_fidelity(fake_pipe, audio_path, "아무 문장입니다.") == []


def test_evaluate_transcription_empty_transcript_is_unavailable(tmp_path):
    from unittest.mock import MagicMock

    from lecture_auto.pipeline.raon_tts import evaluate_transcription

    fake_pipe = MagicMock()
    fake_pipe.stt.return_value = "   "
    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    check = evaluate_transcription(fake_pipe, audio_path, "아무 문장입니다.")
    assert check.status == "unavailable"
    assert check.cer is None

    # Empty expected text (빈 기대문) is unavailable too, even with a real transcript.
    fake_pipe.stt.return_value = "실제 전사된 문장입니다."
    check2 = evaluate_transcription(fake_pipe, audio_path, "   ")
    assert check2.status == "unavailable"
    assert check2.cer is None


def test_evaluate_transcription_content_mismatch_passes_but_records_high_cer(tmp_path):
    """Similar length, different content: gate still passes (no reason triggers)
    but CER records the content divergence -- confirms CER catches what the
    length-ratio/repetition checks miss."""
    from unittest.mock import MagicMock

    from lecture_auto.pipeline.raon_tts import evaluate_transcription

    fake_pipe = MagicMock()
    fake_pipe.stt.return_value = "학생들이 아이디어를 검증하는 과정이 중요합니다."
    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    check = evaluate_transcription(fake_pipe, audio_path, "학생들이 문제를 이해하는 과정이 중요합니다.")
    assert check.status == "pass"
    assert check.reasons == []
    assert check.cer is not None
    assert check.cer >= 0.2


def test_evaluate_transcription_identical_modulo_punctuation_has_zero_cer(tmp_path):
    from unittest.mock import MagicMock

    from lecture_auto.pipeline.raon_tts import evaluate_transcription

    fake_pipe = MagicMock()
    script = "자 다음으로 보실 내용은 디자인씽킹의 핵심 원리입니다."
    # Differs from `script` by whitespace (extra space, a removed space) and
    # punctuation (comma, exclamation mark) only -- content is identical.
    fake_pipe.stt.return_value = "자  다음으로 보실 내용은,디자인씽킹의 핵심원리입니다!"
    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    check = evaluate_transcription(fake_pipe, audio_path, script)
    assert check.status == "pass"
    assert check.cer == 0.0


def test_evaluate_transcription_repetition_is_fail_with_legacy_reason_format(tmp_path):
    from unittest.mock import MagicMock

    from lecture_auto.pipeline.raon_tts import evaluate_transcription

    fake_pipe = MagicMock()
    fake_pipe.stt.return_value = "우리가 문제를 해결해야 하는데 그렇죠 그렇죠 그렇죠 계속해서 진행합니다."
    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    check = evaluate_transcription(fake_pipe, audio_path, "우리가 문제를 해결해야 합니다.")
    assert check.status == "fail"
    # Exact legacy reason-string format (기존 문자열 형식 유지), not just a substring match.
    assert "stt_repetition('그렇죠'*3)" in check.reasons


def test_compute_cer_matches_spec_examples():
    from lecture_auto.pipeline.raon_tts import compute_cer

    assert compute_cer("abc", "abd") == 1 / 3
    assert compute_cer("abc", "ab") == 1 / 3
    assert compute_cer("abc", "abcd") == 1 / 3


def test_compute_cer_empty_reference_is_none():
    from lecture_auto.pipeline.raon_tts import compute_cer

    assert compute_cer("", "anything") is None
    assert compute_cer("   .,!?", "anything") is None


def test_verify_stt_records_status_and_cer_in_slide_trace(tmp_path, monkeypatch):
    """synthesize_raon_slide(verify_stt=True) must not change ok/gate behavior
    (D-08/SPEC_S4a: CER is recorded, not gated) but must surface stt_status
    and stt_cer on the slide's trace line for the web layer to read later."""
    import importlib
    import json as _json

    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("RAON_TRACE", str(trace))
    mod = importlib.reload(importlib.import_module("lecture_auto.pipeline.raon_tts"))
    try:
        pipe = _FakePipe([_tone(5.0)] * 50)
        pipe.stt = lambda audio_path: "첫 문장입니다."  # clean STT match
        out = tmp_path / "slide.wav"

        _, ok = mod.synthesize_raon_slide(pipe, "첫 문장입니다.", out, verify_stt=True)
        assert ok is True

        rows = [_json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines()]
        slide_rows = [r for r in rows if r.get("event") == "slide"]
        assert len(slide_rows) == 1
        assert slide_rows[0]["stt_status"] == "pass"
        assert slide_rows[0]["stt_cer"] == 0.0
    finally:
        monkeypatch.delenv("RAON_TRACE", raising=False)
        importlib.reload(mod)


def test_verify_stt_off_leaves_trace_fields_null(tmp_path, monkeypatch):
    import importlib
    import json as _json

    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("RAON_TRACE", str(trace))
    mod = importlib.reload(importlib.import_module("lecture_auto.pipeline.raon_tts"))
    try:
        pipe = _FakePipe([_tone(5.0)] * 50)
        out = tmp_path / "slide.wav"

        mod.synthesize_raon_slide(pipe, "첫 문장입니다.", out)  # verify_stt=False (default)

        rows = [_json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines()]
        slide_rows = [r for r in rows if r.get("event") == "slide"]
        assert slide_rows[0]["stt_status"] is None
        assert slide_rows[0]["stt_cer"] is None
    finally:
        monkeypatch.delenv("RAON_TRACE", raising=False)
        importlib.reload(mod)


# ---------------------------------------------------------------------------
# S6-a (#1, #9): qc_path writes a SlideQC; None writes nothing; return value
# unchanged either way. TranscriptionCheck's old import path still works.
# ---------------------------------------------------------------------------

def test_qc_path_none_writes_no_file_and_return_value_is_unchanged(tmp_path):
    pipe = _FakePipe([_tone(5.0)] * 50)
    out = tmp_path / "slide.wav"
    result = synthesize_raon_slide(pipe, "첫 문장입니다.", out)
    assert result == (out, True)
    assert not (tmp_path / "slide.wav.qc.json").exists()


def test_qc_path_given_writes_slide_qc_with_segment_fields(tmp_path):
    import json as _json

    s1 = "첫 번째 문장을 아주 충분히 길게 만들어서 확실하게 하나의 독립된 조각이 되도록 열심히 작성하는 문장입니다."
    s2 = "두 번째 문장도 마찬가지로 아주 충분히 길게 만들어서 확실하게 별도의 조각이 되도록 열심히 작성하는 문장입니다."
    text = s1 + " " + s2
    assert len(split_into_segments(text)) == 2, "test assumes exactly 2 top-level segments"

    pipe = _FakePipe([_tone(10.0)] * 10)
    out = tmp_path / "slide.wav"
    qc_path = tmp_path / "slide.wav.qc.json"

    result = synthesize_raon_slide(pipe, text, out, max_seconds=60.0, qc_path=qc_path)
    assert result == (out, True)  # (path, ok) unchanged by adding qc_path

    data = _json.loads(qc_path.read_text(encoding="utf-8"))
    assert data["ok"] is True
    assert data["gate_reasons"] == []
    assert data["synth_version"]
    assert data["created_at"]
    assert data["spoken_text_sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert len(data["segments"]) == 2
    seg0, seg1 = data["segments"]
    assert seg0["index"] == 0 and seg1["index"] == 1
    assert seg0["seed"] in TTS_SEEDS
    assert seg0["call"] == "tts"
    assert seg0["continuation_from"] is None
    # Second segment continues from the first (both passed on the first draw).
    assert seg1["call"] == "tts_continuation"
    assert seg1["continuation_from"] == 0
    assert data["boundary_review"] == []


def test_qc_path_written_even_for_empty_text(tmp_path):
    import json as _json

    pipe = _FakePipe([])
    out = tmp_path / "slide.wav"
    qc_path = tmp_path / "slide.wav.qc.json"
    result = synthesize_raon_slide(pipe, "   ", out, qc_path=qc_path)
    assert result == (out, True)
    data = _json.loads(qc_path.read_text(encoding="utf-8"))
    assert data == {
        "ok": True,
        "gate_reasons": [],
        "stt": None,
        "spoken_text_sha256": data["spoken_text_sha256"],
        "segments": [],
        "boundary_review": [],
        "synth_version": data["synth_version"],
        "created_at": data["created_at"],
    }


def test_transcription_check_import_path_from_raon_tts_is_the_schema_class():
    from lecture_auto.schemas.production import TranscriptionCheck as SchemaCheck

    assert TranscriptionCheck is SchemaCheck


# ---------------------------------------------------------------------------
# S6-c / F6 (#7): redrawing a continuation source after a later segment
# already continued from it must flag that later segment in boundary_review.
#
# raon_tts.py's own second pass (search "Second pass" in synthesize_raon_slide)
# is exactly this case: it redraws a piece against the whole-slide reference
# AFTER every segment (including ones that used it as a tts_continuation
# prefill) has already been generated. This is not a hypothetical -- it is
# the shipped redraw path, evidenced by test_quiet_segment_is_redrawn_against_
# the_slide_level above triggering the same code path.
# ---------------------------------------------------------------------------

def test_boundary_review_flags_downstream_continuation_after_redraw(tmp_path):
    """Segment 0 passes quiet (self-relative gate), segment 1 continues from
    it. The whole-slide reference then reads segment 0 as silence and redraws
    it -- segment 1's join partner is gone, so it must land in boundary_review.
    """
    import json as _json

    sr = 24000
    quiet = _tone(10.0, sr, amp=0.005)
    loud = _tone(10.0, sr, amp=0.3)
    # 1: segment 0's only draw (quiet, passes self-relative).
    # 2: segment 1's tts_continuation draw (loud, passes; continues off segment 0).
    # 3: segment 0's redraw (loud, passes against the real reference).
    pipe = _FakePipe([quiet, loud, loud] + [loud] * 10)

    s1 = "첫 번째 문장을 아주 충분히 길게 만들어서 확실하게 하나의 독립된 조각이 되도록 열심히 작성하는 문장입니다."
    s2 = "두 번째 문장도 마찬가지로 아주 충분히 길게 만들어서 확실하게 별도의 조각이 되도록 열심히 작성하는 문장입니다."
    assert len(split_into_segments(s1 + " " + s2)) == 2, "test assumes exactly 2 top-level segments"

    out = tmp_path / "slide.wav"
    qc_path = tmp_path / "slide.wav.qc.json"
    synthesize_raon_slide(pipe, s1 + " " + s2, out, max_seconds=60.0, qc_path=qc_path)

    data = _json.loads(qc_path.read_text(encoding="utf-8"))
    seg0, seg1 = data["segments"]
    assert seg0["fallback"] is False  # the redraw was adopted, not left failing
    assert seg1["call"] == "tts_continuation"
    assert seg1["continuation_from"] == 0
    assert data["boundary_review"] == [1]


def test_boundary_review_empty_when_no_redraw_replaces_a_continuation_source(tmp_path):
    """Same shape, but both segments come out loud on the first pass -- no
    redraw fires, so nothing needs re-listening to. Proves boundary_review
    isn't populated unconditionally."""
    import json as _json

    sr = 24000
    loud = _tone(10.0, sr, amp=0.3)
    pipe = _FakePipe([loud] * 6)

    s1 = "첫 번째 문장을 아주 충분히 길게 만들어서 확실하게 하나의 독립된 조각이 되도록 열심히 작성하는 문장입니다."
    s2 = "두 번째 문장도 마찬가지로 아주 충분히 길게 만들어서 확실하게 별도의 조각이 되도록 열심히 작성하는 문장입니다."

    out = tmp_path / "slide.wav"
    qc_path = tmp_path / "slide.wav.qc.json"
    synthesize_raon_slide(pipe, s1 + " " + s2, out, max_seconds=60.0, qc_path=qc_path)

    data = _json.loads(qc_path.read_text(encoding="utf-8"))
    assert data["boundary_review"] == []


def test_verify_stt_requested_but_pipe_has_no_stt_records_unavailable(tmp_path):
    """verify_stt=True on a pipe without .stt (e.g. a fake in tests, or a real
    pipe built without the STT head) must record status=unavailable in the QC
    file, not silently leave stt=None as if it was never asked for."""
    import json as _json

    pipe = _FakePipe([_tone(5.0)] * 50)
    assert not hasattr(pipe, "stt")
    out = tmp_path / "slide.wav"
    qc_path = tmp_path / "slide.wav.qc.json"
    _, ok = synthesize_raon_slide(pipe, "첫 문장입니다.", out, verify_stt=True, qc_path=qc_path)
    assert ok is True  # unavailable has no gate_reasons, doesn't fail the slide

    data = _json.loads(qc_path.read_text(encoding="utf-8"))
    assert data["stt"] == {"status": "unavailable", "reasons": [], "transcript": None, "cer": None}


