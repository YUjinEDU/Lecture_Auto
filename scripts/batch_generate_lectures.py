"""Batch lecture video generator for the 5 target lectures.

Runs full end-to-end pipeline:
1. PDF Parsing
2. Slide Rendering (PDF -> PNGs)
3. Lecture-wide plan (sections, recurring examples, time budget) via gpt-5.6-luna
4. Section-by-section script generation (4-8 slides per call, continuous story,
   carry-forward state) via gpt-5.6-luna vision
5. Voice-cloned TTS Audio Synthesis via Raon-Speech-9B (segmented + quality-gated)
6. Video Assembly via ffmpeg -> MP4 (30 minutes each)

Every LLM/TTS call is cached by a SHA-256 of its actual inputs (prompt text,
image bytes, reference voice, model config) via lecture_auto.pipeline.cache --
not by "does a file with this name already exist", so a prompt or reference
voice change regenerates exactly the artifacts affected by it, not none of
them (stale) and not all of them (wasteful).
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from pathlib import Path

from lecture_auto.llm.openai_client import OpenAILLMClient
from lecture_auto.pipeline.cache import content_hash, is_cache_valid, write_cache_hash
from lecture_auto.pipeline.lecture_plan import (
    _PLAN_SYSTEM_PROMPT,
    build_lecture_plan_prompt,
    build_section_prompt,
    generate_lecture_plan,
    generate_section_scripts,
)
from lecture_auto.pipeline.parser_pdf import parse_pdf
from lecture_auto.pipeline.raon_tts import (
    TTS_MODEL_ID,
    TTS_SEEDS,
    TTS_TEMPERATURE,
    load_raon_pipeline,
    synthesize_raon_slide,
)
from lecture_auto.pipeline.renderer import render_slides
from lecture_auto.pipeline.script_gen import generate_script_for_slide_vision, get_professor_system_prompt
from lecture_auto.pipeline.video import assemble_video
from lecture_auto.schemas.lecture_plan import CarryForward, LecturePlan, SectionScriptResult
from lecture_auto.schemas.manifest import LectureStyle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("batch_generator")

TARGET_MINUTES = 30.0  # 30분 영상 목표
REF_VOICE = Path("data/audio_ref/test_variants/ref_combined.wav")

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


def _generate_lecture_plan_cached(
    llm_client, slides, subject: str, name: str, plan_path: Path
) -> LecturePlan:
    prompt_text = build_lecture_plan_prompt(slides, subject, name, TARGET_MINUTES)
    cache_key = content_hash(_PLAN_SYSTEM_PROMPT, prompt_text)

    if is_cache_valid(plan_path, cache_key):
        logger.info("Lecture plan cached, reusing %s", plan_path)
        return LecturePlan(**json.loads(plan_path.read_text(encoding="utf-8")))

    logger.info("Generating lecture plan (whole-slide-set analysis)...")
    plan = generate_lecture_plan(llm_client, slides, subject, name, TARGET_MINUTES)
    plan_path.write_text(json.dumps(plan.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
    write_cache_hash(plan_path, cache_key)
    logger.info("Lecture plan: %d sections covering %d slides", len(plan.sections), len(slides))
    return plan


def _generate_section_scripts_cached(
    llm_client,
    plan: LecturePlan,
    section,
    slides_in_section,
    png_paths_in_section,
    carry_forward: CarryForward | None,
    is_last_section: bool,
    section_result_path: Path,
):
    prompt_text = build_section_prompt(plan, section, slides_in_section, carry_forward, is_last_section)
    image_bytes = b"".join(p.read_bytes() for p in png_paths_in_section)
    carry_forward_repr = carry_forward.model_dump_json() if carry_forward else ""
    cache_key = content_hash(get_professor_system_prompt(), prompt_text, image_bytes, carry_forward_repr)

    if is_cache_valid(section_result_path, cache_key):
        logger.info("Section %r cached, reusing", section.title)
        return SectionScriptResult(**json.loads(section_result_path.read_text(encoding="utf-8")))

    logger.info("Generating section %r (%d slides)...", section.title, len(section.slides))
    result = generate_section_scripts(
        llm_client, plan, section, slides_in_section, png_paths_in_section, carry_forward, is_last_section
    )
    section_result_path.write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_cache_hash(section_result_path, cache_key)
    return result


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
    sections_dir = work_dir / "sections"
    audio_dir = work_dir / "audio"
    video_dir = work_dir / "video"

    for d in (work_dir, rendered_dir, scripts_dir, sections_dir, audio_dir, video_dir, output_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Parse PDF
    logger.info("[1/6] Parsing PDF...")
    slides = parse_pdf(pdf_path)
    slide_count = len(slides)
    slide_by_number = {s.slide_number: s for s in slides}

    # 2. Render PNGs
    logger.info("[2/6] Rendering slides to PNG...")
    png_paths, _ = render_slides(pdf_path, rendered_dir, lec_id)
    png_by_number = {i + 1: p for i, p in enumerate(png_paths)}
    logger.info("Rendered %d PNG images", len(png_paths))

    scripts: dict[int, dict] = {}  # slide_number -> {"target_seconds": ..., "script": ...}

    if clone_source_id:
        # 03/05 share identical body content -- only the cover slide differs.
        # Reuse the source lecture's plan+scripts wholesale, regenerate slide 1.
        src_dir = base_work_dir / clone_source_id
        logger.info("[3-4/6] Cloning plan + body scripts from %s...", src_dir)

        style = LectureStyle(
            density="detailed",
            tone="formal",
            approach="explanatory",
            supplement=f"과목명: {item['subject']}, 강의주제: {item['name']}. 강의시간 30분 맞춤.",
        )
        script_1_path = scripts_dir / "script_001.json"
        prompt_1 = f"과목명 도입부, {item['subject']} 강의로 표지를 설명"
        cache_key_1 = content_hash(get_professor_system_prompt(), prompt_1, png_by_number[1].read_bytes())
        if is_cache_valid(script_1_path, cache_key_1):
            data_1 = json.loads(script_1_path.read_text(encoding="utf-8"))
        else:
            data_1 = generate_script_for_slide_vision(
                client=llm_client,
                slide=slides[0],
                png_path=png_by_number[1],
                style=style,
                target_seconds=20.0,
                prev_slide=None,
                next_slide=slides[1] if slide_count > 1 else None,
                prev_script=None,
            )
            script_1_path.write_text(json.dumps(data_1, ensure_ascii=False, indent=2), encoding="utf-8")
            write_cache_hash(script_1_path, cache_key_1)
        scripts[1] = {"target_seconds": data_1.get("target_seconds", 20.0), "script": data_1.get("script", "")}

        for n in range(2, slide_count + 1):
            src_file = src_dir / "scripts" / f"script_{n:03d}.json"
            dst_file = scripts_dir / f"script_{n:03d}.json"
            shutil.copy2(src_file, dst_file)
            scripts[n] = json.loads(dst_file.read_text(encoding="utf-8"))
        logger.info("Copied %d scripts from source, generated custom slide 1", slide_count - 1)
    else:
        # 3. Lecture plan
        logger.info("[3/6] Building lecture plan...")
        plan_path = work_dir / "lecture_plan.json"
        plan = _generate_lecture_plan_cached(llm_client, slides, item["subject"], item["name"], plan_path)

        # 4. Section-by-section script generation
        logger.info("[4/6] Generating scripts section by section...")
        carry_forward: CarryForward | None = None
        for idx, section in enumerate(plan.sections):
            is_last_section = idx == len(plan.sections) - 1
            slides_in_section = [slide_by_number[n] for n in section.slides]
            png_paths_in_section = [png_by_number[n] for n in section.slides]
            section_result_path = sections_dir / f"section_{idx + 1:03d}.json"

            result = _generate_section_scripts_cached(
                llm_client,
                plan,
                section,
                slides_in_section,
                png_paths_in_section,
                carry_forward,
                is_last_section,
                section_result_path,
            )
            for s in result.slides:
                scripts[s.slide_number] = {"target_seconds": s.target_seconds, "script": s.script}
                (scripts_dir / f"script_{s.slide_number:03d}.json").write_text(
                    json.dumps({"slide_number": s.slide_number, "target_seconds": s.target_seconds, "script": s.script},
                               ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            carry_forward = result.carry_forward

    if tts_pipe is None:
        logger.info("[5-6/6] --skip-tts: leaving TTS/video assembly out, scripts only.")
        return scripts_dir

    # 5. Synthesize Audio with Raon-Speech-9B (segmented + quality-gated, see raon_tts.py)
    logger.info("[5/6] Synthesizing TTS with Raon-Speech-9B & Professor Voice Cloning...")
    wav_paths: list[Path] = []
    ref_voice_bytes = REF_VOICE.read_bytes() if REF_VOICE.exists() else b""

    for n in range(1, slide_count + 1):
        sc = scripts[n]
        script_text = sc.get("script", "")
        out_wav = audio_dir / f"slide_{n:03d}.wav"
        cache_key = content_hash(
            script_text, ref_voice_bytes, TTS_MODEL_ID, str(TTS_TEMPERATURE), str(TTS_SEEDS)
        )
        if is_cache_valid(out_wav, cache_key):
            logger.info("Slide %d/%d audio cached, skipping...", n, slide_count)
        else:
            logger.info("Synthesizing slide %d/%d audio (%d chars)...", n, slide_count, len(script_text))
            synthesize_raon_slide(
                tts_pipe, script_text, out_wav, speaker_audio=REF_VOICE, max_seconds=sc.get("target_seconds")
            )
            write_cache_hash(out_wav, cache_key)
        wav_paths.append(out_wav)

    # 6. Assemble Video
    logger.info("[6/6] Assembling final MP4 video via ffmpeg...")
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
        tts_pipe = load_raon_pipeline(TTS_MODEL_ID, device="cuda:0", dtype="bfloat16")
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
