"""Video assembly module using ffmpeg.

Combines per-slide PNG images and WAV audio files into a single lecture MP4.

Pipeline (per CONTEXT.md D-07/D-08/D-09):
  1. create_slide_clip: PNG + WAV → per-slide MP4 via ffmpeg -loop 1
  2. concat_clips:      list[MP4] → single MP4 via ffmpeg concat demuxer
  3. assemble_video:    orchestrates both steps, cleans up intermediates
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def create_slide_clip(
    png_path: Path,
    wav_path: Path,
    output_path: Path,
    fps: int = 1,
) -> Path:
    """Create a single-slide video clip from a static PNG and a WAV audio file.

    Uses ``ffmpeg -loop 1`` to keep the image displayed for the duration of
    the audio track.  The clip ends when the audio ends (``-shortest``).

    Parameters
    ----------
    png_path:
        Path to the slide PNG image.
    wav_path:
        Path to the slide WAV audio file.
    output_path:
        Destination MP4 file path.
    fps:
        Frame rate for the still-image video stream (default 1 fps is
        sufficient for static slides and keeps file size small).

    Returns
    -------
    Path
        The ``output_path`` that was written.

    Raises
    ------
    RuntimeError
        If ffmpeg exits with a non-zero return code.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-loop", "1",
        "-framerate", str(fps),
        "-i", str(png_path),
        "-i", str(wav_path),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        "-fps_mode", "vfr",
        str(output_path),
    ]

    logger.debug("Creating slide clip: %s", output_path.name)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed for {output_path.name} (exit {result.returncode}):\n"
            f"{result.stderr}"
        )

    logger.debug("Slide clip created: %s", output_path.name)
    return output_path


def concat_clips(clip_paths: list[Path], output_path: Path) -> Path:
    """Concatenate multiple MP4 clips into a single output file.

    Uses the ffmpeg concat demuxer (stream-copy, no re-encoding).

    Parameters
    ----------
    clip_paths:
        Ordered list of MP4 clip paths to concatenate.
    output_path:
        Destination MP4 file path.

    Returns
    -------
    Path
        The ``output_path`` that was written.

    Raises
    ------
    RuntimeError
        If ffmpeg exits with a non-zero return code.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write a temporary concat list file.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False
    ) as concat_file:
        concat_file_path = Path(concat_file.name)
        for clip in clip_paths:
            # Use absolute paths and escape single quotes.
            safe_path = str(clip.resolve()).replace("'", "'\\''")
            concat_file.write(f"file '{safe_path}'\n")

    logger.debug("Concat list written to %s (%d clips)", concat_file_path, len(clip_paths))

    cmd = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_file_path),
        "-c", "copy",
        str(output_path),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    finally:
        concat_file_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg concat failed (exit {result.returncode}):\n{result.stderr}"
        )

    logger.info("Concat complete: %d clips -> %s", len(clip_paths), output_path.name)
    return output_path


def _slide_number_from_path(p: Path) -> int | None:
    """Extract slide number from filenames like ``slide_001.png`` or ``audio_001.wav``.

    Returns None if the number cannot be parsed.
    """
    stem = p.stem  # e.g. "slide_001" or "audio_001"
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def assemble_video(
    png_paths: list[Path],
    wav_paths: list[Path],
    video_dir: Path,
    output_path: Path,
    job_id: str,
) -> Path:
    """Orchestrate per-slide clip creation and final concatenation.

    Matches PNG and WAV files by slide number (parsed from filename), creates
    one MP4 clip per matched pair, concatenates them in order, then removes
    the intermediate clip files.

    Parameters
    ----------
    png_paths:
        Paths to slide PNG images (``slide_NNN.png``).
    wav_paths:
        Paths to slide WAV audio files (``audio_NNN.wav``).
    video_dir:
        Directory for intermediate per-slide MP4 clips.
    output_path:
        Final lecture MP4 output path (e.g. ``output/lecture_{job_id}.mp4``).
    job_id:
        Job identifier — used only for logging.

    Returns
    -------
    Path
        The ``output_path`` that was written.
    """
    video_dir = Path(video_dir)
    video_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(output_path)

    # Build lookup: slide_number -> wav_path
    wav_by_number: dict[int, Path] = {}
    for wav in wav_paths:
        num = _slide_number_from_path(wav)
        if num is not None:
            wav_by_number[num] = wav

    # Build lookup: slide_number -> png_path
    png_by_number: dict[int, Path] = {}
    for png in png_paths:
        num = _slide_number_from_path(png)
        if num is not None:
            png_by_number[num] = png

    # Process slides in sorted order.
    all_slide_numbers = sorted(png_by_number.keys())

    clip_paths: list[Path] = []
    for slide_number in all_slide_numbers:
        png = png_by_number[slide_number]
        wav = wav_by_number.get(slide_number)

        if wav is None:
            logger.warning(
                "Slide %d: no WAV found — skipping (job_id=%s)", slide_number, job_id
            )
            continue

        clip_path = video_dir / f"clip_{slide_number:03d}.mp4"
        logger.info(
            "Creating clip %d/%d: %s + %s -> %s",
            slide_number,
            len(all_slide_numbers),
            png.name,
            wav.name,
            clip_path.name,
        )
        create_slide_clip(png, wav, clip_path)
        clip_paths.append(clip_path)

    if not clip_paths:
        raise RuntimeError("No slide clips were created — cannot assemble video.")

    logger.info("Concatenating %d clips -> %s (job_id=%s)", len(clip_paths), output_path, job_id)
    concat_clips(clip_paths, output_path)

    # Clean up intermediate clip files.
    for clip in clip_paths:
        try:
            clip.unlink()
            logger.debug("Removed intermediate clip: %s", clip.name)
        except OSError as exc:
            logger.warning("Could not remove intermediate clip %s: %s", clip.name, exc)

    logger.info("Video assembly complete: %s (job_id=%s)", output_path, job_id)
    return output_path
