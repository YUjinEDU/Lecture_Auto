"""
Lecture Auto — Interactive CLI orchestrator.

Usage:
    python run.py --pptx lecture.pptx [OPTIONS]

Runs the full 6-stage pipeline:
  1. PPTX Parsing
  2. Slide Rendering (PNG per slide)
  3. VLM Visual Notes (Qwen3-VL)
  4. Script Generation (Claude via claude -p)
  5. TTS Audio Synthesis (Qwen3-TTS)
  6. Video Assembly (ffmpeg)

After each stage the user is prompted [y/n] to continue, allowing inspection
and editing of intermediate files before proceeding.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shutil
import sys
import time
import uuid
from pathlib import Path


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def confirm_step(step_name: str) -> bool:
    """Prompt the user [y/n] before continuing to the next stage.

    An empty Enter press (or 'y'/'yes') is treated as confirmation.

    Args:
        step_name: Display name of the stage just completed.

    Returns:
        True if the user wants to continue, False to abort.
    """
    try:
        response = input(f"\n[{step_name}] Continue to next stage? [y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nInterrupted — aborting.")
        return False
    return response in ("y", "yes", "")


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def print_stage_header(stage_num: int, total: int, name: str) -> None:
    """Print a stage header banner.

    Example output:
        Stage 1/6: PPTX Parsing
        Stage 2/6: Slide Rendering
        Stage 3/6: VLM Analysis
        Stage 4/6: Script Generation
        Stage 5/6: TTS Synthesis
        Stage 6/6: Video Assembly
    """
    print(f"\n{'=' * 60}")
    print(f"  Stage {stage_num}/{total}: {name}")
    print(f"{'=' * 60}")


def print_elapsed(elapsed: float) -> None:
    """Print the elapsed time for a stage."""
    print(f"  Time: {elapsed:.1f}s")


def write_summary(
    output_dir: Path,
    job_id: str,
    pptx_file: Path,
    slide_count: int,
    stage_timings: dict[str, float],
    font_warnings: list[str],
    output_mp4: Path,
    work_dir: Path,
    error: str | None = None,
) -> Path:
    """Write a summary JSON file to output_dir.

    Args:
        output_dir:    Directory to write summary_{job_id}.json into.
        job_id:        Pipeline job identifier.
        pptx_file:     Original PPTX path.
        slide_count:   Number of slides processed.
        stage_timings: Mapping of stage name -> elapsed seconds.
        font_warnings: List of font warning strings from the renderer.
        output_mp4:    Path to the assembled lecture MP4.
        work_dir:      Per-job working directory.
        error:         Optional error message if the pipeline failed.

    Returns:
        Path to the written summary JSON.
    """
    total_seconds = sum(stage_timings.values())
    summary = {
        "job_id": job_id,
        "pptx_file": str(pptx_file),
        "slide_count": slide_count,
        "stage_timings": stage_timings,
        "total_seconds": round(total_seconds, 2),
        "font_warnings": font_warnings,
        "output_mp4": str(output_mp4),
        "work_dir": str(work_dir),
    }
    if error is not None:
        summary["error"] = error

    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / f"summary_{job_id}.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n  Summary written: {summary_path}")
    return summary_path


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Lecture Auto — PPTX to lecture video pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--pptx",
        required=True,
        type=Path,
        help="Path to the input PPTX file",
    )
    parser.add_argument(
        "--density",
        default="detailed",
        choices=["concise", "detailed"],
        help="Script density",
    )
    parser.add_argument(
        "--tone",
        default="formal",
        choices=["formal", "casual"],
        help="Script tone",
    )
    parser.add_argument(
        "--approach",
        default="explanatory",
        choices=["explanatory", "socratic"],
        help="Script approach",
    )
    parser.add_argument(
        "--voice",
        type=Path,
        default=None,
        help="Reference WAV file path for TTS voice cloning (3-second clip)",
    )
    parser.add_argument(
        "--name",
        default="Untitled Lecture",
        help="Lecture name",
    )
    parser.add_argument(
        "--subject",
        default="General",
        help="Subject name",
    )
    parser.add_argument(
        "--audience",
        default="undergraduate",
        help="Target audience",
    )
    parser.add_argument(
        "--minutes",
        type=int,
        default=30,
        help="Target lecture duration in minutes",
    )
    parser.add_argument(
        "--vlm-model",
        default="Qwen/Qwen3-VL-8B-Instruct",
        help="VLM model path or HuggingFace ID",
    )
    parser.add_argument(
        "--tts-model",
        default="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        help="TTS model path or HuggingFace ID",
    )
    return parser


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def main() -> int:
    """Run the interactive 6-stage pipeline.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    # Lazy imports — heavy GPU dependencies are only loaded when each stage runs.
    from lecture_auto.pipeline.parser import parse_pptx
    from lecture_auto.pipeline.renderer import render_slides
    from lecture_auto.pipeline.vlm import generate_visual_notes
    from lecture_auto.pipeline.script_gen import generate_scripts
    from lecture_auto.llm import get_llm_client
    from lecture_auto.pipeline.tts import load_tts, synthesize_audio
    from lecture_auto.pipeline.video import assemble_video
    from lecture_auto.schemas.manifest import LectureStyle, SlideManifest
    from lecture_auto.storage.jobs import JobPaths

    arg_parser = build_arg_parser()
    args = arg_parser.parse_args()

    # ------------------------------------------------------------------
    # Stage 0: Setup
    # ------------------------------------------------------------------
    pptx_path: Path = args.pptx.resolve()
    if not pptx_path.exists():
        print(f"ERROR: PPTX file not found: {pptx_path}", file=sys.stderr)
        return 1

    if args.voice is not None and not args.voice.exists():
        print(f"ERROR: Voice reference file not found: {args.voice}", file=sys.stderr)
        return 1

    job_id = str(uuid.uuid4())
    job_paths = JobPaths(job_id).ensure_dirs()

    # Copy PPTX to input directory so all intermediates are self-contained.
    input_pptx = job_paths.input_dir / pptx_path.name
    shutil.copy2(pptx_path, input_pptx)

    style = LectureStyle(
        density=args.density,
        tone=args.tone,
        approach=args.approach,
    )

    file_sha256 = sha256_file(pptx_path)
    output_dir = Path("output")
    output_mp4 = output_dir / f"lecture_{job_id}.mp4"

    print(f"\nJob ID : {job_id}")
    print(f"PPTX   : {pptx_path}")
    print(f"Work   : {job_paths.job_dir}")
    print(f"Output : {output_mp4}")

    stage_timings: dict[str, float] = {}
    font_warnings: list[str] = []
    slide_count = 0

    # ------------------------------------------------------------------
    # Stage 1: Parse PPTX
    # ------------------------------------------------------------------
    print_stage_header(1, 6, "PPTX Parsing")
    t0 = time.perf_counter()
    try:
        slides = parse_pptx(pptx_path)
        slide_count = len(slides)

        manifest = SlideManifest(
            job_id=job_id,
            file_sha256=file_sha256,
            lecture_name=args.name,
            subject_name=args.subject,
            target_audience=args.audience,
            target_minutes=args.minutes,
            style=style,
            slide_count=slide_count,
            slides=slides,
        )

        manifest_path = job_paths.parsed_dir / "manifest.json"
        manifest_path.write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )

        elapsed = time.perf_counter() - t0
        stage_timings["parse"] = round(elapsed, 2)
        print(f"  Slides extracted : {slide_count}")
        print(f"  Manifest saved   : {manifest_path}")
        print_elapsed(elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        stage_timings["parse"] = round(elapsed, 2)
        print(f"  ERROR in Stage 1: {exc}", file=sys.stderr)
        print(f"  Work dir for inspection: {job_paths.job_dir}", file=sys.stderr)
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error=str(exc))
        return 1

    if not confirm_step("parse"):
        print("Aborted after Stage 1.")
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error="Aborted by user")
        return 0

    # ------------------------------------------------------------------
    # Stage 2: Render slides
    # ------------------------------------------------------------------
    print_stage_header(2, 6, "Slide Rendering")
    t0 = time.perf_counter()
    try:
        png_paths, render_warnings = render_slides(
            pptx_path, job_paths.rendered_dir, job_id
        )
        font_warnings.extend(render_warnings)

        elapsed = time.perf_counter() - t0
        stage_timings["render"] = round(elapsed, 2)
        print(f"  PNGs rendered : {len(png_paths)}")
        if render_warnings:
            print(f"  Font warnings ({len(render_warnings)}):")
            for w in render_warnings:
                print(f"    - {w}")
        print_elapsed(elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        stage_timings["render"] = round(elapsed, 2)
        print(f"  ERROR in Stage 2: {exc}", file=sys.stderr)
        print(f"  Work dir for inspection: {job_paths.job_dir}", file=sys.stderr)
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error=str(exc))
        return 1

    if not confirm_step("render"):
        print("Aborted after Stage 2.")
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error="Aborted by user")
        return 0

    # ------------------------------------------------------------------
    # Stage 3: VLM visual notes
    # ------------------------------------------------------------------
    print_stage_header(3, 6, "VLM Analysis")
    t0 = time.perf_counter()
    try:
        llm_client = get_llm_client()
        vlm_notes = generate_visual_notes(
            llm_client, slides, job_paths.rendered_dir, job_paths.vlm_dir
        )

        elapsed = time.perf_counter() - t0
        stage_timings["vlm"] = round(elapsed, 2)
        print(f"  Visual notes generated : {len(vlm_notes)}")
        print(f"  Notes saved to         : {job_paths.vlm_dir}")
        print_elapsed(elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        stage_timings["vlm"] = round(elapsed, 2)
        print(f"  ERROR in Stage 3: {exc}", file=sys.stderr)
        print(f"  Work dir for inspection: {job_paths.job_dir}", file=sys.stderr)
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error=str(exc))
        return 1

    if not confirm_step("vlm"):
        print("Aborted after Stage 3.")
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error="Aborted by user")
        return 0

    # ------------------------------------------------------------------
    # Stage 4: Script generation
    # ------------------------------------------------------------------
    print_stage_header(4, 6, "Script Generation")
    t0 = time.perf_counter()
    try:
        scripts = generate_scripts(
            slides,
            [n.model_dump() for n in vlm_notes],
            manifest,
            job_paths.scripts_dir,
            client=llm_client,
        )

        elapsed = time.perf_counter() - t0
        stage_timings["script_gen"] = round(elapsed, 2)
        print(f"  Scripts generated : {len(scripts)}")
        print(f"  Scripts saved to  : {job_paths.scripts_dir}")
        print_elapsed(elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        stage_timings["script_gen"] = round(elapsed, 2)
        print(f"  ERROR in Stage 4: {exc}", file=sys.stderr)
        print(f"  Work dir for inspection: {job_paths.job_dir}", file=sys.stderr)
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error=str(exc))
        return 1

    if not confirm_step("scripts"):
        print("Aborted after Stage 4.")
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error="Aborted by user")
        return 0

    # ------------------------------------------------------------------
    # Stage 5: TTS audio synthesis
    # ------------------------------------------------------------------
    print_stage_header(5, 6, "TTS Synthesis")
    t0 = time.perf_counter()
    try:
        tts_model = load_tts(args.tts_model)
        wav_paths = synthesize_audio(
            tts_model,
            [s.model_dump() for s in scripts],
            job_paths.audio_dir,
            args.voice,
        )

        elapsed = time.perf_counter() - t0
        stage_timings["tts"] = round(elapsed, 2)
        print(f"  Audio files generated : {len(wav_paths)}")
        print(f"  Audio saved to        : {job_paths.audio_dir}")
        print_elapsed(elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        stage_timings["tts"] = round(elapsed, 2)
        print(f"  ERROR in Stage 5: {exc}", file=sys.stderr)
        print(f"  Work dir for inspection: {job_paths.job_dir}", file=sys.stderr)
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error=str(exc))
        return 1

    if not confirm_step("tts"):
        print("Aborted after Stage 5.")
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error="Aborted by user")
        return 0

    # ------------------------------------------------------------------
    # Stage 6: Video assembly
    # ------------------------------------------------------------------
    print_stage_header(6, 6, "Video Assembly")
    t0 = time.perf_counter()
    try:
        video_dir = job_paths.job_dir / "video"
        video_dir.mkdir(parents=True, exist_ok=True)

        output_dir.mkdir(parents=True, exist_ok=True)

        assemble_video(png_paths, wav_paths, video_dir, output_mp4, job_id)

        elapsed = time.perf_counter() - t0
        stage_timings["video"] = round(elapsed, 2)
        print(f"  MP4 created : {output_mp4}")
        print_elapsed(elapsed)
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        stage_timings["video"] = round(elapsed, 2)
        print(f"  ERROR in Stage 6: {exc}", file=sys.stderr)
        print(f"  Work dir for inspection: {job_paths.job_dir}", file=sys.stderr)
        write_summary(output_dir, job_id, pptx_path, slide_count, stage_timings,
                      font_warnings, output_mp4, job_paths.job_dir, error=str(exc))
        return 1

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    summary_path = write_summary(
        output_dir, job_id, pptx_path, slide_count, stage_timings,
        font_warnings, output_mp4, job_paths.job_dir,
    )

    total = sum(stage_timings.values())
    print(f"\n{'=' * 60}")
    print("  Pipeline complete!")
    print(f"{'=' * 60}")
    print(f"  Slides    : {slide_count}")
    print(f"  Total time: {total:.1f}s")
    print(f"  MP4       : {output_mp4}")
    print(f"  Summary   : {summary_path}")
    print(f"  Work dir  : {job_paths.job_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
