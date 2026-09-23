"""Video assembly module using ffmpeg.

Combines per-slide PNG images and WAV audio files into a single lecture MP4.

For downloaded artifacts we prefer a single encode pass over clip-by-clip
concatenation because it produces more reliable timestamps across players and
is materially faster for large slide decks.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import wave
from pathlib import Path

from lecture_auto.pipeline.tts import merge_audio

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
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
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


def _wav_duration_seconds(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate() or 1
    return max(frames / float(rate), 0.05)


def assemble_video(
    png_paths: list[Path],
    wav_paths: list[Path],
    video_dir: Path,
    output_path: Path,
    job_id: str,
    strict: bool = False,
) -> Path:
    """Assemble the final lecture MP4 in a single encode pass.

    Matches PNG and WAV files by slide number, builds an ffmpeg concat manifest
    with per-slide image durations derived from the WAV lengths, merges the WAV
    files once, and encodes the final MP4 directly.

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
    strict:
        When True, a PNG with no matching WAV raises ``FileNotFoundError``
        (naming the missing slide number(s)) instead of being silently
        skipped with a warning. Batch production runs want this; interactive/
        demo drivers keep the permissive default.

    Returns
    -------
    Path
        The ``output_path`` that was written.

    Raises
    ------
    FileNotFoundError
        If ``strict=True`` and one or more PNGs have no matching WAV.
    """
    video_dir = Path(video_dir)
    video_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(output_path)

    wav_by_number: dict[int, Path] = {}
    for wav in wav_paths:
        num = _slide_number_from_path(wav)
        if num is not None:
            wav_by_number[num] = wav

    png_by_number: dict[int, Path] = {}
    for png in png_paths:
        num = _slide_number_from_path(png)
        if num is not None:
            png_by_number[num] = png

    all_slide_numbers = sorted(png_by_number.keys())
    slide_pairs: list[tuple[Path, Path]] = []
    missing_slides: list[int] = []
    for slide_number in all_slide_numbers:
        png = png_by_number[slide_number]
        wav = wav_by_number.get(slide_number)
        # In strict mode also treat a resolved-but-nonexistent WAV path as
        # missing: batch callers pre-build one wav_path per slide number
        # unconditionally, so "no entry for this slide" alone never fires --
        # the on-disk check is what actually protects a caller that resolved
        # a path whose file was never written.
        if wav is None or (strict and not wav.exists()):
            missing_slides.append(slide_number)
            continue
        slide_pairs.append((png, wav))

    if missing_slides:
        if strict:
            raise FileNotFoundError(
                f"No WAV found for slide(s) {missing_slides} (job_id={job_id})"
            )
        for slide_number in missing_slides:
            logger.warning(
                "Slide %d: no WAV found — skipping (job_id=%s)", slide_number, job_id
            )

    if not slide_pairs:
        raise RuntimeError("No slide/audio pairs were found — cannot assemble video.")

    merged_audio_path = video_dir / f"{job_id}_merged_audio.wav"
    slideshow_manifest_path: Path | None = None
    total_duration = 0.0

    try:
        # Merge exactly the WAVs resolved above, in slide order -- not
        # everything glob-matches in the directory (S1-a).
        merge_audio([wav for _, wav in slide_pairs], merged_audio_path)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as manifest_file:
            slideshow_manifest_path = Path(manifest_file.name)
            for png, wav in slide_pairs:
                duration = _wav_duration_seconds(wav)
                total_duration += duration
                safe_path = str(png.resolve()).replace("'", "'\\''")
                manifest_file.write(f"file '{safe_path}'\n")
                manifest_file.write(f"duration {duration:.6f}\n")
            last_png = str(slide_pairs[-1][0].resolve()).replace("'", "'\\''")
            manifest_file.write(f"file '{last_png}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(slideshow_manifest_path),
            "-i", str(merged_audio_path),
            "-t", f"{total_duration:.6f}",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-shortest",
            str(output_path),
        ]

        logger.info(
            "Encoding slideshow video: %d slides -> %s (job_id=%s)",
            len(slide_pairs),
            output_path.name,
            job_id,
        )
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg slideshow assembly failed (exit {result.returncode}):\n{result.stderr}"
            )
    finally:
        if slideshow_manifest_path is not None:
            slideshow_manifest_path.unlink(missing_ok=True)
        merged_audio_path.unlink(missing_ok=True)

    logger.info("Video assembly complete: %s (job_id=%s)", output_path, job_id)
    return output_path
