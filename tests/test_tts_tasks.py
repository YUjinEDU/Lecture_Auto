"""Tests for lecture_auto/tasks/tts_tasks.py -- F3/S6-b resumable API TTS task.

Mocks the TTS engine (``_get_tts``), Redis (``publish_progress``), and the
merge/assemble stage functions -- no GPU/network/Redis/ffmpeg. ``JobPaths`` is
redirected to ``tmp_path`` via ``JOB_OUTPUT_ROOT`` (it otherwise defaults
under ``/data/work``), matching the pattern in tests/test_vlm_tasks.py.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lecture_auto.pipeline.cache import content_hash, write_cache_hash
from lecture_auto.schemas.manifest import LectureStyle, SlideManifest, SlideRecord
from lecture_auto.storage.jobs import JobPaths


def _make_manifest(slide_count: int = 2) -> SlideManifest:
    slides = [
        SlideRecord(slide_index=i, slide_number=i + 1, png_path=f"slide_{i + 1:03d}.png", shapes=[])
        for i in range(slide_count)
    ]
    return SlideManifest(
        job_id=str(uuid.uuid4()),
        file_sha256="abc123",
        lecture_name="Test Lecture",
        subject_name="CS101",
        target_audience="undergrad",
        target_minutes=30,
        style=LectureStyle(density="concise", tone="formal", approach="explanatory"),
        slide_count=slide_count,
        slides=slides,
    )


def _setup_job_dirs(tmp_path: Path, manifest: SlideManifest, scripts: dict[int, str]) -> JobPaths:
    jp = JobPaths(manifest.job_id, root=tmp_path)
    jp.ensure_dirs()
    jp.manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    for slide in manifest.slides:
        (jp.rendered_dir / slide.png_path).write_bytes(b"fake png")
    for n, text in scripts.items():
        (jp.scripts_dir / f"script_{n:03d}.json").write_text(
            json.dumps({"script": text}), encoding="utf-8"
        )
    return jp


class _FakeEngine:
    """Writes bytes derived from the text it was asked to synthesize, so a
    test can prove *which* slides were actually (re)run, and exposes
    ``_model_path`` the way ``QwenTTSEngine`` does for the cache key."""

    _model_path = "fake-model"

    def __init__(self):
        self.calls: list[str] = []

    def synthesize_slide(self, text, output_path, *, voice_ref_path=None, voice_ref_text=None):
        self.calls.append(Path(output_path).name)
        Path(output_path).write_bytes(f"AUDIO:{text}".encode())
        return output_path


def _engine_cache_key(text: str) -> str:
    return content_hash(text, b"", f"{_FakeEngine.__name__}:fake-model")


def _run_synth_task(tmp_path, manifest, engine, mock_merge=None, mock_assemble=None):
    from lecture_auto.tasks.tts_tasks import synthesize_job_task

    with patch("lecture_auto.tasks.tts_tasks.publish_progress"), \
         patch("lecture_auto.tasks.tts_tasks._get_tts", return_value=engine), \
         patch("lecture_auto.pipeline.tts.merge_audio", mock_merge or MagicMock()) as merge_mock, \
         patch("lecture_auto.pipeline.video.assemble_video", mock_assemble or MagicMock()) as assemble_mock, \
         patch(
             "lecture_auto.storage.jobs.os.environ.get",
             side_effect=lambda k, d=None: str(tmp_path) if k == "JOB_OUTPUT_ROOT" else d,
         ):
        result = synthesize_job_task.run(manifest.job_id)
    return result, merge_mock, assemble_mock


# ---------------------------------------------------------------------------
# #5: F3 -- script-changed slides resynthesize even though a WAV exists,
# unchanged slides skip, a slide with no script fails loudly.
# ---------------------------------------------------------------------------

def test_unchanged_script_skips_resynthesis(tmp_path):
    manifest = _make_manifest(1)
    jp = _setup_job_dirs(tmp_path, manifest, {1: "hello"})
    engine = _FakeEngine()
    wav_path = jp.audio_dir / "audio_001.wav"
    wav_path.write_bytes(b"AUDIO:hello")
    write_cache_hash(wav_path, _engine_cache_key("hello"))

    result, *_ = _run_synth_task(tmp_path, manifest, engine)

    assert engine.calls == []  # cache valid -- not re-synthesized
    assert result == {"job_id": manifest.job_id, "total": 1, "skipped": 1}
    assert wav_path.read_bytes() == b"AUDIO:hello"  # untouched


def test_changed_script_resynthesizes_even_though_wav_exists(tmp_path):
    """This is exactly what the base commit's WAV-existence-only skip check
    got wrong (F3): disabling the cache-key check (reverting to `if
    wav_path.exists(): skip`) makes this test fail, because the stale WAV is
    present and would be served forever."""
    manifest = _make_manifest(1)
    jp = _setup_job_dirs(tmp_path, manifest, {1: "new text"})
    engine = _FakeEngine()
    wav_path = jp.audio_dir / "audio_001.wav"
    wav_path.write_bytes(b"AUDIO:old text")  # stale WAV for a since-edited script
    write_cache_hash(wav_path, _engine_cache_key("old text"))

    result, *_ = _run_synth_task(tmp_path, manifest, engine)

    assert engine.calls == ["audio_001.wav"]
    assert result["skipped"] == 0
    assert wav_path.read_bytes() == b"AUDIO:new text"


def test_missing_script_fails_loudly_not_silently_skipped(tmp_path):
    manifest = _make_manifest(1)
    _setup_job_dirs(tmp_path, manifest, {})  # no script_001.json at all
    engine = _FakeEngine()

    with pytest.raises(FileNotFoundError):
        _run_synth_task(tmp_path, manifest, engine)
    assert engine.calls == []


def test_regenerate_slide_tts_task_writes_cache_hash(tmp_path):
    """F3's cache check has to see regenerate_slide_tts_task's output as
    fresh too, or the next synthesize_job_task run would redo it."""
    from lecture_auto.pipeline.cache import is_cache_valid
    from lecture_auto.tasks.tts_tasks import regenerate_slide_tts_task

    manifest = _make_manifest(1)
    jp = _setup_job_dirs(tmp_path, manifest, {1: "regenerated text"})
    engine = _FakeEngine()

    with patch("lecture_auto.tasks.tts_tasks._get_tts", return_value=engine), \
         patch(
             "lecture_auto.storage.jobs.os.environ.get",
             side_effect=lambda k, d=None: str(tmp_path) if k == "JOB_OUTPUT_ROOT" else d,
         ):
        regenerate_slide_tts_task.run(manifest.job_id, 1)

    wav_path = jp.audio_dir / "audio_001.wav"
    assert is_cache_valid(wav_path, _engine_cache_key("regenerated text"))


# ---------------------------------------------------------------------------
# #6: F3 -- assembly merges exactly the resolved slide WAVs, ignoring an
# unrelated WAV that happens to sit in the same audio directory.
# ---------------------------------------------------------------------------

def test_merge_and_assemble_do_not_mix_unrelated_wav_files(tmp_path):
    manifest = _make_manifest(2)
    jp = _setup_job_dirs(tmp_path, manifest, {1: "one", 2: "two"})
    engine = _FakeEngine()
    # A directory glob (the old behavior) would have picked this up too.
    (jp.audio_dir / "unrelated_extra.wav").write_bytes(b"UNRELATED")

    result, merge_mock, assemble_mock = _run_synth_task(tmp_path, manifest, engine)

    assert result["total"] == 2
    merge_mock.assert_called_once()
    merged_names = [Path(p).name for p in merge_mock.call_args.args[0]]
    assert merged_names == ["audio_001.wav", "audio_002.wav"]

    assemble_mock.assert_called_once()
    assembled_names = [Path(p).name for p in assemble_mock.call_args.args[1]]
    assert assembled_names == ["audio_001.wav", "audio_002.wav"]
    assert assemble_mock.call_args.kwargs.get("strict") is True
