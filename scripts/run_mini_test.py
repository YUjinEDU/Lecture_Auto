"""Mini 3-slide end-to-end test script.

Generates:
1. Parse & Render first 3 slides of Lecture 1
2. Generate scripts for 3 slides using gpt-5.6-luna (professor style)
3. Synthesize audio with Raon-Speech-9B using sample_v3_combined reference
4. Assemble final mini test MP4 video
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path

from lecture_auto.llm.openai_client import OpenAILLMClient
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.renderer import render_slides
from lecture_auto.pipeline.script_gen import build_script_prompt, _parse_script_json
from lecture_auto.pipeline.raon_tts import load_raon_pipeline, synthesize_raon_slide
from lecture_auto.pipeline.video import assemble_video
from lecture_auto.schemas.manifest import LectureStyle

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mini_test")

PDF_PATH = Path("data/PDF/AI현업문제해결/02-디자인씽킹 개요.pdf")
REF_AUDIO = Path("data/audio_ref/test_variants/ref_combined.wav")
WORK_DIR = Path("data/work_mini_test")
OUT_MP4 = Path("output/test_01_mini_3slides.mp4")
NUM_SLIDES = 3

def main():
    logger.info("=== Starting Mini 3-Slide End-to-End Test ===")
    rendered_dir = WORK_DIR / "rendered"
    scripts_dir = WORK_DIR / "scripts"
    audio_dir = WORK_DIR / "audio"
    video_dir = WORK_DIR / "video"
    OUT_MP4.parent.mkdir(parents=True, exist_ok=True)

    for d in (WORK_DIR, rendered_dir, scripts_dir, audio_dir, video_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Parse PDF
    logger.info("[1/4] Parsing PDF (first %d slides)...", NUM_SLIDES)
    all_slides = parse_pdf(PDF_PATH)
    slides = all_slides[:NUM_SLIDES]
    logger.info("Parsed %d slides", len(slides))

    # 2. Render PNGs
    logger.info("[2/4] Rendering slides to PNG...")
    all_pngs, _ = render_slides(PDF_PATH, rendered_dir, "mini_test")
    png_paths = all_pngs[:NUM_SLIDES]
    logger.info("Using %d PNGs: %s", len(png_paths), [p.name for p in png_paths])

    # 3. Generate Scripts
    logger.info("[3/4] Generating scripts with gpt-5.6-luna...")
    llm_client = OpenAILLMClient()
    style = LectureStyle(
        density="detailed",
        tone="formal",
        approach="explanatory",
        supplement="과목명: AI활용현업문제해결, 강의주제: 02-디자인씽킹 개요. 실제 교수님 강의 육성 톤앤매너.",
    )
    target_seconds = 45.0  # 테스트용 45초/슬라이드

    scripts = []
    prev_script = None

    for idx, slide in enumerate(slides):
        script_file = scripts_dir / f"script_{idx+1:03d}.json"
        if script_file.exists():
            logger.info("Slide %d script already exists, loading...", idx + 1)
            data = json.loads(script_file.read_text(encoding="utf-8"))
        else:
            prompt = build_script_prompt(
                slide=slide,
                vlm_note=None,
                style=style,
                target_seconds=target_seconds,
                prev_slide=slides[idx - 1] if idx > 0 else None,
                prev_script=prev_script,
                next_slide=slides[idx + 1] if idx + 1 < len(slides) else None,
            )
            logger.info("Generating script for slide %d...", idx + 1)
            raw = llm_client.complete_text(prompt)
            data = _parse_script_json(raw, idx, idx + 1)
            script_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        scripts.append(data)
        prev_script = data.get("script", "")
        logger.info("Slide %d Script (%d chars): %s", idx + 1, len(prev_script), prev_script[:60] + "...")

    # 4. Synthesize TTS with Raon-Speech-9B
    logger.info("[4/4] Checking/Synthesizing %d slide audios with Raon-Speech-9B...", len(scripts))
    tts_pipe = None

    wav_paths = []
    for idx, sc in enumerate(scripts, start=1):
        out_wav = audio_dir / f"slide_{idx:03d}.wav"
        if out_wav.exists() and out_wav.stat().st_size > 1000:
            logger.info("Slide %d audio already exists (%d bytes), skipping...", idx, out_wav.stat().st_size)
        else:
            if tts_pipe is None:
                tts_pipe = load_raon_pipeline("KRAFTON/Raon-Speech-9B", device="cuda:0", dtype="bfloat16")
            logger.info("Synthesizing slide %d audio (%d chars)...", idx, len(sc.get("script", "")))
            synthesize_raon_slide(tts_pipe, sc.get("script", ""), out_wav, speaker_audio=REF_AUDIO)
            logger.info("Slide %d audio saved to: %s", idx, out_wav)
        wav_paths.append(out_wav)

    # 5. Assemble Video
    logger.info("[5/5] Assembling final test MP4 video via ffmpeg...")
    assemble_video(png_paths, wav_paths, video_dir, OUT_MP4, "mini_test")
    logger.info("=" * 60)
    logger.info("SUCCESS! Mini test MP4 video created at: %s", OUT_MP4)
    logger.info("=" * 60)

if __name__ == "__main__":
    main()
