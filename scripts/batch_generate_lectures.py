"""Batch lecture video generator for the 5 target lectures.

Runs full end-to-end pipeline:
1. PDF Parsing & Manifest creation
2. Slide Rendering (PDF -> PNGs)
3. Script Generation via gpt-5.6-luna with Professor Speaking Style
4. Voice-cloned TTS Audio Synthesis via Raon-Speech-9B
5. Video Assembly via ffmpeg -> MP4 (30 minutes each)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from lecture_auto.llm.openai_client import OpenAILLMClient
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.renderer import render_slides
from lecture_auto.pipeline.script_gen import build_script_prompt, _parse_script_json
from lecture_auto.pipeline.raon_tts import load_raon_pipeline, synthesize_raon_slide
from lecture_auto.pipeline.video import assemble_video
from lecture_auto.schemas.manifest import LectureStyle, SlideManifest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("batch_generator")

TARGET_MINUTES = 30.0  # 30분 영상 목표
REF_VOICE = Path("data/audio_ref/professor_voice_ref.wav")

LECTURES = [
    {
        "id": "01_AI현업_02_디자인씽킹개요",
        "name": "02-디자인씽킹 개요",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/02-디자인씽킹 개요.pdf"),
        "output_mp4": Path("output/01_AI현업_02_디자인씽킹개요.mp4"),
    },
    {
        "id": "02_AI현업_03_고객문제이해",
        "name": "03-고객 문제 이해",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/03-고객 문제 이해.pdf"),
        "output_mp4": Path("output/02_AI현업_03_고객문제이해.mp4"),
    },
    {
        "id": "03_AI현업_04_문제정의와아이디에이션",
        "name": "04-문제정의와 아이디에이션",
        "subject": "AI활용현업문제해결",
        "pdf": Path("data/PDF/AI현업문제해결/04-문제정의와 아이디에이션.pdf"),
        "output_mp4": Path("output/03_AI현업_04_문제정의와아이디에이션.mp4"),
    },
    {
        "id": "04_종합설계_02_고객문제이해및정의",
        "name": "02_고객 문제 이해 및 정의",
        "subject": "종합설계",
        "pdf": Path("data/PDF/종합설계/02_고객 문제 이해 및 정의.pdf"),
        "output_mp4": Path("output/04_종합설계_02_고객문제이해및정의.mp4"),
    },
    {
        "id": "05_종합설계_03_문제정의와아이디에이션",
        "name": "03_문제정의와 아이디에이션",
        "subject": "종합설계",
        "pdf": Path("data/PDF/종합설계/03_문제정의와 아이디에이션.pdf"),
        "output_mp4": Path("output/05_종합설계_03_문제정의와아이디에이션.mp4"),
        "clone_from": "03_AI현업_04_문제정의와아이디에이션",
    },
]


def process_lecture(
    item: dict,
    llm_client: OpenAILLMClient,
    tts_pipe,
    base_work_dir: Path,
    output_dir: Path,
) -> Path:
    lec_id = item["id"]
    pdf_path = item["pdf"].resolve()
    out_mp4 = item["output_mp4"].resolve()
    clone_source_id = item.get("clone_from")

    logger.info("=" * 60)
    logger.info("Processing [%s] %s (%s)", lec_id, item["name"], item["subject"])
    logger.info("PDF: %s", pdf_path)
    logger.info("=" * 60)

    work_dir = base_work_dir / lec_id
    rendered_dir = work_dir / "rendered"
    scripts_dir = work_dir / "scripts"
    audio_dir = work_dir / "audio"
    video_dir = work_dir / "video"

    for d in (work_dir, rendered_dir, scripts_dir, audio_dir, video_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Parse PDF
    logger.info("[1/5] Parsing PDF...")
    slides = parse_pdf(pdf_path)
    slide_count = len(slides)
    target_seconds = (TARGET_MINUTES * 60.0) / slide_count
    logger.info("Parsed %d slides. Target duration: %.1f sec/slide (~30 min total)", slide_count, target_seconds)

    # 2. Render PNGs
    logger.info("[2/5] Rendering slides to PNG...")
    png_paths, _ = render_slides(pdf_path, rendered_dir, lec_id)
    logger.info("Rendered %d PNG images", len(png_paths))

    # 3. Generate Scripts
    logger.info("[3/5] Generating Scripts with gpt-5.6-luna (Professor style)...")
    style = LectureStyle(
        density="detailed",
        tone="formal",
        approach="explanatory",
        supplement=f"과목명: {item['subject']}, 강의주제: {item['name']}. 강의시간 30분 맞춤.",
    )

    scripts: list[dict] = []
    prev_script: str | None = None

    if clone_source_id:
        # Optimization: Clone body from 03_AI현업_04, only generate slide 1!
        src_scripts_dir = base_work_dir / clone_source_id / "scripts"
        logger.info("Cloning body scripts from %s...", src_scripts_dir)

        # Slide 1 (Custom opening for 종합설계)
        prompt_1 = build_script_prompt(
            slide=slides[0],
            vlm_note=None,
            style=style,
            target_seconds=target_seconds,
            prev_slide=None,
            prev_script=None,
            next_slide=slides[1] if slide_count > 1 else None,
        )
        raw_1 = llm_client.complete_text(prompt_1)
        data_1 = _parse_script_json(raw_1, 0, 1)
        scripts.append(data_1)
        (scripts_dir / "script_001.json").write_text(json.dumps(data_1, ensure_ascii=False, indent=2), encoding="utf-8")

        # Slides 2..N copied from source
        for idx in range(1, slide_count):
            src_file = src_scripts_dir / f"script_{idx+1:03d}.json"
            dst_file = scripts_dir / f"script_{idx+1:03d}.json"
            shutil.copy2(src_file, dst_file)
            scripts.append(json.loads(dst_file.read_text(encoding="utf-8")))
        logger.info("Copied %d scripts from source, generated custom slide 1", slide_count - 1)
    else:
        for idx, slide in enumerate(slides):
            script_file = scripts_dir / f"script_{idx+1:03d}.json"
            if script_file.exists():
                logger.info("Slide %d/%d script exists, loading...", idx+1, slide_count)
                data = json.loads(script_file.read_text(encoding="utf-8"))
            else:
                logger.info("Generating script for slide %d/%d...", idx+1, slide_count)
                prompt = build_script_prompt(
                    slide=slide,
                    vlm_note=None,
                    style=style,
                    target_seconds=target_seconds,
                    prev_slide=slides[idx - 1] if idx > 0 else None,
                    prev_script=prev_script,
                    next_slide=slides[idx + 1] if idx + 1 < slide_count else None,
                )
                raw = llm_client.complete_text(prompt)
                data = _parse_script_json(raw, idx, idx + 1)
                script_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

            scripts.append(data)
            prev_script = data.get("script", "")

    # 4. Synthesize Audio with Raon-Speech-9B
    logger.info("[4/5] Synthesizing TTS with Raon-Speech-9B & Professor Voice Cloning...")
    wav_paths: list[Path] = []

    if clone_source_id:
        src_audio_dir = base_work_dir / clone_source_id / "audio"
        # Synthesize slide 1
        wav_1 = audio_dir / "slide_001.wav"
        if not wav_1.exists():
            logger.info("Synthesizing customized slide 1 audio for %s...", item["subject"])
            synthesize_raon_slide(tts_pipe, scripts[0].get("script", ""), wav_1, speaker_audio=REF_VOICE)
        wav_paths.append(wav_1)

        # Copy/link remaining audio
        for idx in range(1, slide_count):
            src_wav = src_audio_dir / f"slide_{idx+1:03d}.wav"
            dst_wav = audio_dir / f"slide_{idx+1:03d}.wav"
            if not dst_wav.exists():
                shutil.copy2(src_wav, dst_wav)
            wav_paths.append(dst_wav)
        logger.info("Audio cloning complete: 1 synthesized + %d reused", slide_count - 1)
    else:
        for idx, sc in enumerate(scripts, start=1):
            out_wav = audio_dir / f"slide_{idx:03d}.wav"
            if out_wav.exists() and out_wav.stat().st_size > 1000:
                logger.info("Slide %d/%d audio exists, skipping...", idx, len(scripts))
            else:
                logger.info("Synthesizing slide %d/%d audio (%d chars)...", idx, len(scripts), len(sc.get("script", "")))
                synthesize_raon_slide(tts_pipe, sc.get("script", ""), out_wav, speaker_audio=REF_VOICE)
            wav_paths.append(out_wav)

    # 5. Assemble Video
    logger.info("[5/5] Assembling final MP4 video via ffmpeg...")
    assemble_video(png_paths, wav_paths, video_dir, out_mp4, lec_id)
    logger.info("Video successfully created at: %s", out_mp4)
    return out_mp4


def main():
    parser = argparse.ArgumentParser(description="Batch lecture video generation")
    parser.add_argument("--only", type=str, default=None, help="Run only specific lecture id or index (1-5)")
    parser.add_argument("--skip-tts", action="store_true", help="Skip TTS synthesis (test script/render only)")
    args = parser.parse_args()

    base_work = Path("data/work_batch")
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Initializing LLM client (FactChat gpt-5.6-luna)...")
    llm_client = OpenAILLMClient()

    tts_pipe = None
    if not args.skip_tts:
        logger.info("Loading Raon-Speech-9B TTS model on cuda:0...")
        tts_pipe = load_raon_pipeline("KRAFTON/Raon-Speech-9B", device="cuda:0", dtype="bfloat16")
        logger.info("Raon-Speech-9B ready!")

    selected = LECTURES
    if args.only:
        if args.only.isdigit():
            idx = int(args.only) - 1
            selected = [LECTURES[idx]]
        else:
            selected = [lec for lec in LECTURES if args.only in lec["id"]]

    logger.info("Lectures to generate: %d", len(selected))
    results = []

    for lec in selected:
        t0 = time.time()
        mp4_path = process_lecture(lec, llm_client, tts_pipe, base_work, output_dir)
        elapsed = time.time() - t0
        results.append((lec["id"], mp4_path, elapsed))

    logger.info("=" * 60)
    logger.info("ALL COMPLETED!")
    for lid, path, el in results:
        logger.info("  [%s] -> %s (Time: %.1f min)", lid, path, el / 60.0)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
