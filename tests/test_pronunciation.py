"""Tests for lecture_auto/pipeline/pronunciation.py (S6-d).

Pure-function tests plus a cache-key integration check against
scripts/batch_generate_lectures.py's _tts_cache_key -- no GPU/network.
"""
from __future__ import annotations

from pathlib import Path

from lecture_auto.pipeline.pronunciation import apply_pronunciation, load_pronunciation_entries
from scripts.batch_generate_lectures import _tts_cache_key

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Captured at master c61a75a (before S6) via:
#   _tts_cache_key("API를 쓰는 예시입니다", b"ref", 20.0)
# with entries=() (the only signature that existed then). Any change to this
# value means an all-unapproved dictionary is no longer a byte-identical
# no-op for the cache key, which would force-regenerate the shipped 01/04
# lecture audio the SPEC explicitly forbids (S6 SPEC "금지" section).
_GOLDEN_CACHE_KEY = "2f750b294b513712204313de9a1927a8177e660721dbb1e8ed5e842d5ccff23f"


# ---------------------------------------------------------------------------
# apply_pronunciation: approved-only, word boundary, longest-match-first
# ---------------------------------------------------------------------------

def test_unapproved_entries_are_never_applied():
    entries = [{"written": "API", "spoken": "에이피아이", "approved": False}]
    assert apply_pronunciation("API 문서를 봅니다", entries) == "API 문서를 봅니다"


def test_approved_entry_is_applied():
    entries = [{"written": "API", "spoken": "에이피아이", "approved": True}]
    assert apply_pronunciation("API 문서를 봅니다", entries) == "에이피아이 문서를 봅니다"


def test_korean_particle_glued_to_written_term_still_matches():
    """The main real-world case: Python's \\b treats Hangul as a word char,
    so \\bAPI\\b would silently fail to match "API를". Disabling the
    ASCII-boundary regex (swapping it for plain str.replace, which has no
    boundary at all) makes this test pass for the wrong reason but breaks
    test_does_not_match_inside_a_longer_ascii_word below -- the two together
    pin the actual boundary behavior."""
    entries = [{"written": "API", "spoken": "에이피아이", "approved": True}]
    assert apply_pronunciation("API를 호출합니다", entries) == "에이피아이를 호출합니다"


def test_does_not_match_inside_a_longer_ascii_word():
    entries = [{"written": "API", "spoken": "에이피아이", "approved": True}]
    assert apply_pronunciation("APIs와 RAPID를 비교합니다", entries) == "APIs와 RAPID를 비교합니다"


def test_longer_written_term_wins_over_shorter_overlapping_one():
    entries = [
        {"written": "API", "spoken": "에이피아이", "approved": True},
        {"written": "REST API", "spoken": "레스트 에이피아이", "approved": True},
    ]
    assert apply_pronunciation("REST API 설계", entries) == "레스트 에이피아이 설계"


def test_only_approved_entries_apply_even_when_mixed():
    entries = [
        {"written": "API", "spoken": "에이피아이", "approved": True},
        {"written": "GPU", "spoken": "지피유", "approved": False},
    ]
    assert apply_pronunciation("API와 GPU", entries) == "에이피아이와 GPU"


def test_no_approved_entries_returns_text_unchanged_object_semantics():
    assert apply_pronunciation("변화 없음", []) == "변화 없음"
    assert apply_pronunciation("변화 없음", [{"written": "x", "spoken": "y", "approved": False}]) == "변화 없음"


def test_apply_pronunciation_never_mutates_input_text_or_entries():
    text = "API 예시"
    entries = [{"written": "API", "spoken": "에이피아이", "approved": True}]
    entries_copy = [dict(e) for e in entries]
    apply_pronunciation(text, entries)
    assert text == "API 예시"  # str is immutable, but pin the contract anyway
    assert entries == entries_copy  # entries list/dicts untouched


# ---------------------------------------------------------------------------
# load_pronunciation_entries: the committed config/pronunciation.yaml
# ---------------------------------------------------------------------------

def test_load_pronunciation_entries_reads_committed_yaml():
    entries = load_pronunciation_entries(_REPO_ROOT / "config" / "pronunciation.yaml")
    assert len(entries) >= 3
    assert all(e["approved"] is False for e in entries)
    assert all({"written", "spoken", "approved"} <= e.keys() for e in entries)


def test_load_pronunciation_entries_missing_file_returns_empty_list(tmp_path):
    assert load_pronunciation_entries(tmp_path / "does_not_exist.yaml") == []


# ---------------------------------------------------------------------------
# Cache key integration (S6 SPEC #8): approved-only dictionary changes only
# the affected slide's key; the shipped all-false dictionary is a byte-
# identical no-op against the pre-S6 key (golden value above).
# ---------------------------------------------------------------------------

def test_committed_pronunciation_yaml_is_a_cache_key_no_op():
    """All-approved:false (the shipped state) must reproduce the exact
    pre-S6 cache key -- otherwise every already-produced 01/04 lecture WAV
    would look stale the moment this ships (SPEC's explicit prohibition)."""
    entries = load_pronunciation_entries(_REPO_ROOT / "config" / "pronunciation.yaml")
    assert _tts_cache_key("API를 쓰는 예시입니다", b"ref", 20.0, entries) == _GOLDEN_CACHE_KEY
    assert _tts_cache_key("API를 쓰는 예시입니다", b"ref", 20.0) == _GOLDEN_CACHE_KEY  # entries omitted


def test_approving_an_entry_changes_the_cache_key_only_for_affected_text():
    unapproved = [{"written": "API", "spoken": "에이피아이", "approved": False}]
    approved = [{"written": "API", "spoken": "에이피아이", "approved": True}]

    # Slide whose script mentions "API": key changes once approved.
    key_before = _tts_cache_key("API를 쓰는 예시입니다", b"ref", 20.0, unapproved)
    key_after = _tts_cache_key("API를 쓰는 예시입니다", b"ref", 20.0, approved)
    assert key_before != key_after
    assert key_before == _GOLDEN_CACHE_KEY

    # A different slide that never mentions "API" is unaffected either way.
    other_before = _tts_cache_key("전혀 다른 내용입니다", b"ref", 20.0, unapproved)
    other_after = _tts_cache_key("전혀 다른 내용입니다", b"ref", 20.0, approved)
    assert other_before == other_after
