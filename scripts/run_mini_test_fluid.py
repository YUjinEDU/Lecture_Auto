"""Mini 3-slide end-to-end test -- exercises the exact code path
scripts/batch_generate_lectures.py uses (no separate copy of the vision
prompt or TTS synthesis logic; see lecture_auto/pipeline/script_gen.py and
lecture_auto/pipeline/raon_tts.py).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from lecture_auto.llm.openai_client import OpenAILLMClient
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.renderer import render_slides
from lecture_auto.pipeline.script_gen import generate_script_for_slide_vision
from lecture_auto.pipeline.raon_tts import load_raon_pipeline, synthesize_raon_slide
from lecture_auto.pipeline.video import assemble_video
from lecture_auto.schemas.manifest import LectureStyle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fluid_mini_test")

PDF_PATH = Path("data/PDF/AI현업문제해결/02-디자인씽킹 개요.pdf")
REF_AUDIO = Path("data/audio_ref/test_variants/ref_combined.wav")
WORK_DIR = Path("data/work_mini_test_fluid")
OUT_MP4 = Path("output/test_01_mini_3slides_fluid.mp4")
NUM_SLIDES = 3
TARGET_SECONDS = 30.0  # same order of magnitude as the real 30-min/slide-count target


def main():
    logger.info("=== Starting Vision-based Fluid Mini Test (shared pipeline) ===")
    rendered_dir = WORK_DIR / "rendered"
    scripts_dir = WORK_DIR / "scripts"
    audio_dir = WORK_DIR / "audio"
    video_dir = WORK_DIR / "video"
    OUT_MP4.parent.mkdir(parents=True, exist_ok=True)

    for d in (WORK_DIR, rendered_dir, scripts_dir, audio_dir, video_dir):
        d.mkdir(parents=True, exist_ok=True)

    logger.info("[1/4] Parsing PDF + rendering slides to PNG...")
    slides = parse_pdf(PDF_PATH)[:NUM_SLIDES]
    all_pngs, _ = render_slides(PDF_PATH, rendered_dir, "mini_fluid")
    png_paths = all_pngs[:NUM_SLIDES]
    logger.info("Rendered PNGs: %s", [p.name for p in png_paths])

    logger.info("[2/4] Generating Vision-based scripts with gpt-5.6-luna...")
    client = OpenAILLMClient()
    style = LectureStyle(
        density="detailed",
        tone="formal",
        approach="explanatory",
        supplement="과목명: AI 활용 현업문제해결, 강의주제: 디자인씽킹 개요.",
    )

    scripts: list[dict] = []
    prev_script: str | None = None
    for idx, slide in enumerate(slides):
        data = generate_script_for_slide_vision(
            client=client,
            slide=slide,
            png_path=png_paths[idx],
            style=style,
            target_seconds=TARGET_SECONDS,
            prev_slide=slides[idx - 1] if idx > 0 else None,
            next_slide=slides[idx + 1] if idx + 1 < len(slides) else None,
            prev_script=prev_script,
        )
        (scripts_dir / f"script_{idx+1:03d}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        scripts.append(data)
        prev_script = data.get("script", "")
        logger.info("Slide %d Script (%d chars): %s", idx + 1, len(prev_script), prev_script)

    logger.info("[3/4] Loading Raon-Speech-9B and synthesizing audio (single-pass)...")
    tts_pipe = load_raon_pipeline("KRAFTON/Raon-Speech-9B", device="cuda:0", dtype="bfloat16")

    wav_paths = []
    for idx, sc in enumerate(scripts, start=1):
        out_wav = audio_dir / f"slide_{idx:03d}.wav"
        synthesize_raon_slide(tts_pipe, sc.get("script", ""), out_wav, speaker_audio=REF_AUDIO, max_seconds=TARGET_SECONDS)
        wav_paths.append(out_wav)

    logger.info("[4/4] Assembling MP4 video via ffmpeg...")
    assemble_video(png_paths, wav_paths, video_dir, OUT_MP4, "mini_fluid")
    logger.info("=" * 60)
    logger.info("SUCCESS! Fluid Vision Mini Test MP4 created at: %s", OUT_MP4)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
