"""Unit tests for lecture_auto.pipeline.video module.

All ffmpeg subprocess calls are mocked — no ffmpeg binary required.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import lecture_auto.pipeline.video as video_module
from lecture_auto.pipeline.video import (
    assemble_video,
    concat_clips,
    create_slide_clip,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dummy_file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00")
    return path


def _success_result() -> MagicMock:
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.returncode = 0
    r.stderr = ""
    return r


def _failure_result(msg: str = "error") -> MagicMock:
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.returncode = 1
    r.stderr = msg
    return r


# ---------------------------------------------------------------------------
# Test 1: create_slide_clip uses ffmpeg -loop 1 and -shortest
# ---------------------------------------------------------------------------

def test_create_slide_clip_ffmpeg_command(tmp_path):
    """`create_slide_clip` must call ffmpeg with -loop 1, -shortest, libx264."""
    png = _make_dummy_file(tmp_path / "slide_001.png")
    wav = _make_dummy_file(tmp_path / "audio_001.wav")
    out = tmp_path / "clip_001.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        result = create_slide_clip(png, wav, out)

    assert result == out
    assert mock_run.call_count == 1
    cmd = mock_run.call_args.args[0]
    assert "ffmpeg" in cmd[0]
    assert "-loop" in cmd
    assert "1" in cmd
    assert "-shortest" in cmd
    assert "libx264" in cmd
    assert str(png) in cmd
    assert str(wav) in cmd
    assert str(out) in cmd


def test_create_slide_clip_stillimage_tune(tmp_path):
    """`create_slide_clip` must pass -tune stillimage."""
    png = _make_dummy_file(tmp_path / "slide_001.png")
    wav = _make_dummy_file(tmp_path / "audio_001.wav")
    out = tmp_path / "clip_001.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        create_slide_clip(png, wav, out)

    cmd = mock_run.call_args.args[0]
    assert "-tune" in cmd
    tune_idx = cmd.index("-tune")
    assert cmd[tune_idx + 1] == "stillimage"


def test_create_slide_clip_raises_on_ffmpeg_failure(tmp_path):
    """`create_slide_clip` raises RuntimeError when ffmpeg returns non-zero."""
    png = _make_dummy_file(tmp_path / "slide_001.png")
    wav = _make_dummy_file(tmp_path / "audio_001.wav")
    out = tmp_path / "clip_001.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _failure_result("some ffmpeg error")
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            create_slide_clip(png, wav, out)


# ---------------------------------------------------------------------------
# Test 2: concat_clips writes correct concat format and calls ffmpeg -f concat
# ---------------------------------------------------------------------------

def test_concat_clips_uses_concat_demuxer(tmp_path):
    """`concat_clips` must call ffmpeg with -f concat and -safe 0."""
    clips = [
        _make_dummy_file(tmp_path / "clip_001.mp4"),
        _make_dummy_file(tmp_path / "clip_002.mp4"),
    ]
    out = tmp_path / "lecture.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        result = concat_clips(clips, out)

    assert result == out
    cmd = mock_run.call_args.args[0]
    assert "-f" in cmd
    f_idx = cmd.index("-f")
    assert cmd[f_idx + 1] == "concat"
    assert "-safe" in cmd
    assert "-c" in cmd
    assert "copy" in cmd
    assert str(out) in cmd


def test_concat_clips_raises_on_ffmpeg_failure(tmp_path):
    """`concat_clips` raises RuntimeError when ffmpeg returns non-zero."""
    clips = [_make_dummy_file(tmp_path / "clip_001.mp4")]
    out = tmp_path / "lecture.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _failure_result("concat error")
        with pytest.raises(RuntimeError, match="ffmpeg concat failed"):
            concat_clips(clips, out)


def test_concat_clips_cleans_up_temp_file(tmp_path):
    """`concat_clips` must delete the temporary concat list file after running."""
    clips = [_make_dummy_file(tmp_path / "clip_001.mp4")]
    out = tmp_path / "lecture.mp4"

    captured_concat_path: list[Path] = []

    original_run = subprocess.run

    def capturing_run(cmd, **kwargs):
        # Find the -i argument (the concat list file path)
        if "-i" in cmd:
            i_idx = cmd.index("-i")
            captured_concat_path.append(Path(cmd[i_idx + 1]))
        return _success_result()

    with patch("lecture_auto.pipeline.video.subprocess.run", side_effect=capturing_run):
        concat_clips(clips, out)

    # The temp file should have been deleted
    if captured_concat_path:
        assert not captured_concat_path[0].exists(), "Temp concat file was not cleaned up"


# ---------------------------------------------------------------------------
# Test 3: assemble_video orchestrates clips then concatenation
# ---------------------------------------------------------------------------

def test_assemble_video_calls_create_and_concat(tmp_path):
    """`assemble_video` must call create_slide_clip per pair and concat_clips once."""
    png_dir = tmp_path / "rendered"
    wav_dir = tmp_path / "audio"
    video_dir = tmp_path / "video"
    out = tmp_path / "output" / "lecture_test.mp4"

    pngs = [_make_dummy_file(png_dir / f"slide_{i:03d}.png") for i in [1, 2]]
    wavs = [_make_dummy_file(wav_dir / f"audio_{i:03d}.wav") for i in [1, 2]]

    with patch.object(video_module, "create_slide_clip") as mock_create, \
         patch.object(video_module, "concat_clips") as mock_concat:
        mock_create.side_effect = lambda png, wav, clip_path: clip_path
        mock_concat.side_effect = lambda clips, output_path: output_path

        result = assemble_video(pngs, wavs, video_dir, out, job_id="test-job")

    assert result == out
    assert mock_create.call_count == 2
    assert mock_concat.call_count == 1


# ---------------------------------------------------------------------------
# Test 4: Final output path follows expected pattern
# ---------------------------------------------------------------------------

def test_assemble_video_output_path(tmp_path):
    """The output path passed into assemble_video is returned unchanged."""
    pngs = [_make_dummy_file(tmp_path / f"slide_{i:03d}.png") for i in [1]]
    wavs = [_make_dummy_file(tmp_path / f"audio_{i:03d}.wav") for i in [1]]
    out = tmp_path / "output" / "lecture_abc123.mp4"

    with patch.object(video_module, "create_slide_clip") as mock_create, \
         patch.object(video_module, "concat_clips") as mock_concat:
        mock_create.side_effect = lambda png, wav, clip_path: clip_path
        mock_concat.side_effect = lambda clips, output_path: output_path

        result = assemble_video(pngs, wavs, tmp_path / "video", out, job_id="abc123")

    assert result == out


# ---------------------------------------------------------------------------
# Test 5: ffmpeg subprocess is called with correct arguments (integration)
# ---------------------------------------------------------------------------

def test_create_slide_clip_subprocess_kwargs(tmp_path):
    """`create_slide_clip` must call subprocess.run with capture_output=True, text=True."""
    png = _make_dummy_file(tmp_path / "slide_001.png")
    wav = _make_dummy_file(tmp_path / "audio_001.wav")
    out = tmp_path / "clip_001.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        create_slide_clip(png, wav, out)

    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("capture_output") is True
    assert kwargs.get("text") is True
    assert kwargs.get("check") is False


# ---------------------------------------------------------------------------
# Test 6: Missing WAV for a slide is skipped gracefully
# ---------------------------------------------------------------------------

def test_assemble_video_skips_missing_wav(tmp_path):
    """Slides without a matching WAV file are skipped with a warning (no error)."""
    pngs = [
        _make_dummy_file(tmp_path / "slide_001.png"),
        _make_dummy_file(tmp_path / "slide_002.png"),
    ]
    # Only WAV for slide 1; slide 2 has no audio
    wavs = [_make_dummy_file(tmp_path / "audio_001.wav")]
    out = tmp_path / "lecture.mp4"

    with patch.object(video_module, "create_slide_clip") as mock_create, \
         patch.object(video_module, "concat_clips") as mock_concat:
        mock_create.side_effect = lambda png, wav, clip_path: clip_path
        mock_concat.side_effect = lambda clips, output_path: output_path

        result = assemble_video(pngs, wavs, tmp_path / "video", out, job_id="skip-test")

    # Only one clip should have been created (slide 1)
    assert mock_create.call_count == 1
    # concat still called with the one clip
    assert mock_concat.call_count == 1


# ---------------------------------------------------------------------------
# Test 7: Intermediate clip files are cleaned up after concat
# ---------------------------------------------------------------------------

def test_assemble_video_cleans_up_intermediate_clips(tmp_path):
    """Intermediate per-slide clip files must be deleted after concat."""
    video_dir = tmp_path / "video"
    pngs = [_make_dummy_file(tmp_path / "slide_001.png")]
    wavs = [_make_dummy_file(tmp_path / "audio_001.wav")]
    out = tmp_path / "lecture.mp4"

    # Simulate create_slide_clip actually creating the file so unlink() works
    def fake_create(png, wav, clip_path):
        _make_dummy_file(clip_path)
        return clip_path

    with patch.object(video_module, "create_slide_clip", side_effect=fake_create), \
         patch.object(video_module, "concat_clips") as mock_concat:
        mock_concat.side_effect = lambda clips, output_path: output_path

        assemble_video(pngs, wavs, video_dir, out, job_id="cleanup-test")

    # All clip_*.mp4 files in video_dir should be removed
    remaining_clips = list(video_dir.glob("clip_*.mp4"))
    assert remaining_clips == [], f"Expected no clips, found: {remaining_clips}"
