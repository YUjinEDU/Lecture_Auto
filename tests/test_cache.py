"""Tests for lecture_auto.pipeline.cache -- pure filesystem/hash logic, no GPU/LLM."""
from __future__ import annotations

from lecture_auto.pipeline.cache import content_hash, is_cache_valid, write_cache_hash


def test_content_hash_deterministic():
    assert content_hash("a", "b") == content_hash("a", "b")


def test_content_hash_is_order_and_boundary_sensitive():
    assert content_hash("a", "b") != content_hash("b", "a")
    assert content_hash("a", "b") != content_hash("ab")


def test_content_hash_accepts_mixed_str_and_bytes():
    assert content_hash("text", b"bytes", "0.85") != content_hash("text", b"bytes", "1.2")


def test_is_cache_valid_roundtrip(tmp_path):
    artifact = tmp_path / "out.wav"
    artifact.write_bytes(b"fake-audio")
    h = content_hash("script text", b"ref-audio-bytes", "model-x", "0.85")

    assert not is_cache_valid(artifact, h)
    write_cache_hash(artifact, h)
    assert is_cache_valid(artifact, h)


def test_is_cache_valid_detects_changed_input(tmp_path):
    artifact = tmp_path / "out.wav"
    artifact.write_bytes(b"fake-audio")
    write_cache_hash(artifact, content_hash("old script"))

    assert not is_cache_valid(artifact, content_hash("new script"))


def test_is_cache_valid_false_when_artifact_missing(tmp_path):
    artifact = tmp_path / "missing.wav"
    h = content_hash("x")
    write_cache_hash(artifact, h)

    assert not is_cache_valid(artifact, h)


def test_is_cache_valid_false_when_hash_sidecar_missing(tmp_path):
    artifact = tmp_path / "out.wav"
    artifact.write_bytes(b"fake-audio")

    assert not is_cache_valid(artifact, content_hash("anything"))
