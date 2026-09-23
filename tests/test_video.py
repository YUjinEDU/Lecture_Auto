"""Unit tests for lecture_auto.pipeline.video module.

All ffmpeg subprocess calls are mocked — no ffmpeg binary required.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest
import soundfile as sf

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


def _make_silence_wav(path: Path, duration_seconds: float = 0.1, sample_rate: int = 24000) -> Path:
    """Write a real, readable silence WAV -- `assemble_video` reads WAV
    duration/content for real (via `wave`/`soundfile`) even though ffmpeg
    itself is mocked out, so a fake `\\x00` byte file fails those reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.zeros(int(sample_rate * duration_seconds), dtype=np.float32)
    sf.write(str(path), samples, sample_rate)
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
# Test 3: assemble_video does a single-pass ffmpeg slideshow encode
# ---------------------------------------------------------------------------
# NOTE: the current `assemble_video` builds one ffmpeg concat-demuxer manifest
# (image durations from the WAVs) and does a single `subprocess.run` -- it no
# longer calls `create_slide_clip`/`concat_clips` per pair. These tests were
# written against an older per-clip implementation and mocked those instead,
# which is why they only ever failed on the fake-WAV read (never on ffmpeg
# actually running with garbage PNG bytes). Updated to mock `subprocess.run`,
# matching how the sibling `create_slide_clip`/`concat_clips` tests above
# already mock ffmpeg.

def test_assemble_video_calls_create_and_concat(tmp_path):
    """`assemble_video` must merge audio and do exactly one ffmpeg encode call."""
    png_dir = tmp_path / "rendered"
    wav_dir = tmp_path / "audio"
    video_dir = tmp_path / "video"
    out = tmp_path / "output" / "lecture_test.mp4"

    pngs = [_make_dummy_file(png_dir / f"slide_{i:03d}.png") for i in [1, 2]]
    wavs = [_make_silence_wav(wav_dir / f"audio_{i:03d}.wav") for i in [1, 2]]

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        result = assemble_video(pngs, wavs, video_dir, out, job_id="test-job")

    assert result == out
    assert mock_run.call_count == 1
    cmd = mock_run.call_args.args[0]
    assert "ffmpeg" in cmd[0]
    assert str(out) in cmd


# ---------------------------------------------------------------------------
# Test 4: Final output path follows expected pattern
# ---------------------------------------------------------------------------

def test_assemble_video_output_path(tmp_path):
    """The output path passed into assemble_video is returned unchanged."""
    pngs = [_make_dummy_file(tmp_path / f"slide_{i:03d}.png") for i in [1]]
    wavs = [_make_silence_wav(tmp_path / f"audio_{i:03d}.wav") for i in [1]]
    out = tmp_path / "output" / "lecture_abc123.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
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
    wavs = [_make_silence_wav(tmp_path / "audio_001.wav")]
    out = tmp_path / "lecture.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        result = assemble_video(pngs, wavs, tmp_path / "video", out, job_id="skip-test")

    assert result == out
    # Only one ffmpeg encode call, covering the one resolved slide.
    assert mock_run.call_count == 1


# ---------------------------------------------------------------------------
# Test 7: Intermediate/temp files are cleaned up after assembly
# ---------------------------------------------------------------------------
# The current single-pass encoder never writes per-slide clip_*.mp4 files (it
# builds one concat manifest + merges audio once) -- it cleans up the merged
# audio temp file and the manifest temp file instead. Updated from the old
# per-clip assumption to check the cleanup that actually happens now.

def test_assemble_video_cleans_up_intermediate_clips(tmp_path):
    """No per-slide clip files and no leftover merged-audio temp file."""
    video_dir = tmp_path / "video"
    pngs = [_make_dummy_file(tmp_path / "slide_001.png")]
    wavs = [_make_silence_wav(tmp_path / "audio_001.wav")]
    out = tmp_path / "lecture.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        assemble_video(pngs, wavs, video_dir, out, job_id="cleanup-test")

    remaining_clips = list(video_dir.glob("clip_*.mp4"))
    assert remaining_clips == [], f"Expected no clips, found: {remaining_clips}"
    remaining_merged_audio = list(video_dir.glob("*_merged_audio.wav"))
    assert remaining_merged_audio == [], f"merged audio temp file not cleaned up: {remaining_merged_audio}"


# ---------------------------------------------------------------------------
# S1-a: assemble_video merges exactly the resolved slide WAVs, not the whole dir
# ---------------------------------------------------------------------------

def test_assemble_video_merges_only_resolved_slides(tmp_path):
    """An unrelated WAV in the same directory (e.g. a stale slide_999.wav)
    must not be pulled into the merged audio track used for the video."""
    png_dir = tmp_path / "rendered"
    wav_dir = tmp_path / "audio"
    video_dir = tmp_path / "video"
    out = tmp_path / "lecture.mp4"

    pngs = [_make_dummy_file(png_dir / f"slide_{i:03d}.png") for i in [1, 2]]
    wavs = [
        _make_silence_wav(wav_dir / "slide_001.wav", duration_seconds=0.1),
        _make_silence_wav(wav_dir / "slide_002.wav", duration_seconds=0.2),
    ]
    # Unrelated file that would glob-match if assemble_video merged by directory.
    _make_silence_wav(wav_dir / "slide_999.wav", duration_seconds=5.0)

    real_merge_audio = video_module.merge_audio
    merged_lengths: list[int] = []

    def capturing_merge(source, output_path, **kwargs):
        result = real_merge_audio(source, output_path, **kwargs)
        data, _sr = sf.read(str(result))
        merged_lengths.append(len(data))
        return result

    with patch.object(video_module, "merge_audio", side_effect=capturing_merge) as mock_merge, \
         patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        assemble_video(pngs, wavs, video_dir, out, job_id="s1a-test")

    # merge_audio must be called with the explicit list, not the directory.
    merge_source = mock_merge.call_args.args[0]
    assert list(merge_source) == wavs

    expected_len = int(24000 * 0.1) + int(24000 * 0.2)
    assert merged_lengths == [expected_len]


# ---------------------------------------------------------------------------
# S1-b: strict mode raises on a missing WAV instead of skipping
# ---------------------------------------------------------------------------

def test_assemble_video_strict_raises_on_missing_wav(tmp_path):
    """strict=True: a PNG with no matching WAV raises FileNotFoundError
    (naming the slide) and ffmpeg is never invoked."""
    pngs = [
        _make_dummy_file(tmp_path / "slide_001.png"),
        _make_dummy_file(tmp_path / "slide_002.png"),
    ]
    wavs = [_make_silence_wav(tmp_path / "audio_001.wav")]  # slide 2 missing
    out = tmp_path / "lecture.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        with pytest.raises(FileNotFoundError, match="2"):
            assemble_video(pngs, wavs, tmp_path / "video", out, job_id="strict-test", strict=True)
        mock_run.assert_not_called()


def test_assemble_video_strict_raises_when_wav_path_resolved_but_file_absent(tmp_path):
    """strict=True: a slide with a resolved WAV *path* whose file was never
    actually written on disk must also raise, not just a slide with no path
    at all (batch callers always resolve one path per slide number)."""
    pngs = [_make_dummy_file(tmp_path / "slide_001.png")]
    # Path is well-formed and slide-number-matched, but nothing was written there.
    ghost_wav = tmp_path / "audio_001.wav"
    out = tmp_path / "lecture.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        with pytest.raises(FileNotFoundError, match="1"):
            assemble_video(pngs, [ghost_wav], tmp_path / "video", out, job_id="ghost-test", strict=True)
        mock_run.assert_not_called()


def test_assemble_video_strict_false_still_skips(tmp_path):
    """Default (strict=False) behavior is unchanged: missing WAV is skipped,
    not an error."""
    pngs = [
        _make_dummy_file(tmp_path / "slide_001.png"),
        _make_dummy_file(tmp_path / "slide_002.png"),
    ]
    wavs = [_make_silence_wav(tmp_path / "audio_001.wav")]
    out = tmp_path / "lecture.mp4"

    with patch("lecture_auto.pipeline.video.subprocess.run") as mock_run:
        mock_run.return_value = _success_result()
        result = assemble_video(pngs, wavs, tmp_path / "video", out, job_id="non-strict-test")

    assert result == out
    assert mock_run.call_count == 1
