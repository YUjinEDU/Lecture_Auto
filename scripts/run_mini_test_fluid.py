"""Mini 3-slide end-to-end test with Vision and Fluid TTS.

Features:
1. Feeds high-resolution slide PNG images directly to gpt-5.6-luna (Multimodal Vision).
2. Generates concise, natural spoken lecture scripts (140-180 chars, ~25-30s per slide).
3. Synthesizes fluid single-pass audio with Raon-Speech-9B (no awkward sentence splices).
4. Assembles clean, professional MP4 video.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
import soundfile as sf
import numpy as np

from lecture_auto.llm.openai_client import OpenAILLMClient
from lecture_auto.pipeline.renderer import render_slides
from lecture_auto.pipeline.script_gen import get_professor_system_prompt, _parse_script_json
from lecture_auto.pipeline.raon_tts import load_raon_pipeline
from lecture_auto.pipeline.video import assemble_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fluid_mini_test")

PDF_PATH = Path("data/PDF/AI현업문제해결/02-디자인씽킹 개요.pdf")
REF_AUDIO = Path("data/audio_ref/test_variants/ref_combined.wav")
WORK_DIR = Path("data/work_mini_test_fluid")
OUT_MP4 = Path("output/test_01_mini_3slides_fluid.mp4")
NUM_SLIDES = 3


def synthesize_fluid_slide(pipe, script: str, out_path: Path, ref_audio: Path) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info("Synthesizing fluid audio (%d chars) -> %s...", len(script), out_path.name)
    audio, sr = pipe.tts(script, speaker_audio=str(ref_audio))
    
    if hasattr(audio, "squeeze"):
        audio_np = audio.squeeze().cpu().float().numpy()
    else:
        audio_np = np.array(audio, dtype=np.float32)

    # Clean leading/trailing silence only
    threshold = 0.005
    active = np.where(np.abs(audio_np) > threshold)[0]
    if len(active) > 0:
        start = max(0, active[0] - int(sr * 0.05))
        end = min(len(audio_np), active[-1] + int(sr * 0.05))
        audio_np = audio_np[start:end]

    peak = np.max(np.abs(audio_np))
    if peak > 0:
        audio_np = (audio_np / peak) * 0.92

    sf.write(str(out_path), audio_np, sr)
    logger.info("Saved fluid audio: %s (%.2fs)", out_path.name, len(audio_np) / sr)
    return out_path


def main():
    logger.info("=== Starting Vision-based Fluid Mini Test ===")
    rendered_dir = WORK_DIR / "rendered"
    scripts_dir = WORK_DIR / "scripts"
    audio_dir = WORK_DIR / "audio"
    video_dir = WORK_DIR / "video"
    OUT_MP4.parent.mkdir(parents=True, exist_ok=True)

    for d in (WORK_DIR, rendered_dir, scripts_dir, audio_dir, video_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1. Render slides to PNG
    logger.info("[1/4] Rendering slides to PNG...")
    all_pngs, _ = render_slides(PDF_PATH, rendered_dir, "mini_fluid")
    png_paths = all_pngs[:NUM_SLIDES]
    logger.info("Rendered PNGs: %s", [p.name for p in png_paths])

    # 2. Generate Vision-based scripts with gpt-5.6-luna
    logger.info("[2/4] Generating Vision-based scripts with gpt-5.6-luna...")
    client = OpenAILLMClient(vlm_model="gpt-5.6-luna")
    system_prompt = get_professor_system_prompt()

    scripts = []
    prev_script = None

    for idx, png_path in enumerate(png_paths, start=1):
        script_file = scripts_dir / f"script_{idx:03d}.json"
        image_b64 = base64.b64encode(png_path.read_bytes()).decode("utf-8")

        user_prompt = f"""이 슬라이드 이미지({idx}번 슬라이드)를 직접 보고, 실제 대학 강의를 진행하는 김인국 교수님의 생생한 강의 육성 대본을 작성해 주세요.

[강의 기본 정보]
- 과목명: AI 활용 현업문제해결
- 주제: 디자인씽킹 개요
- 현재 슬라이드 번호: {idx} / 3

[대본 작성 핵심 지침]
1. 슬라이드에 보이는 그림, 다이어그램, 텍스트, 배치를 직접 눈으로 보고 학생들에게 설명하듯이 이야기하십시오.
2. 발화 길이는 약 25~30초 분량(공백 포함 140~180자 내외)으로 핵심을 명쾌하게 짚고 일상 비유를 들어 자연스럽게 풀어내십시오.
3. 교수님 고유 화법("자, 여러분", "우리가", "~라고 볼 수가 있겠죠?", "~인 겁니다")을 반드시 반영하십시오.
4. 반드시 지정된 JSON 형식으로만 응답하십시오."""

        if prev_script:
            user_prompt += f"""\n\n[이전 슬라이드에서 했던 말]:\n"{prev_script}" """

        logger.info("Generating script for slide %d with Vision...", idx)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"}},
                    {"type": "text", "text": user_prompt},
                ],
            },
        ]
        raw = client.chat(messages)
        data = _parse_script_json(raw, idx - 1, idx)
        script_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        scripts.append(data)
        prev_script = data.get("script", "")
        logger.info("Slide %d Script (%d chars): %s", idx, len(prev_script), prev_script)

    # 3. Synthesize Fluid Audio
    logger.info("[3/4] Loading Raon-Speech-9B and synthesizing fluid audios...")
    tts_pipe = load_raon_pipeline("KRAFTON/Raon-Speech-9B", device="cuda:0", dtype="bfloat16")

    wav_paths = []
    for idx, sc in enumerate(scripts, start=1):
        out_wav = audio_dir / f"slide_{idx:03d}.wav"
        synthesize_fluid_slide(tts_pipe, sc.get("script", ""), out_wav, REF_AUDIO)
        wav_paths.append(out_wav)

    # 4. Assemble Video
    logger.info("[4/4] Assembling MP4 video via ffmpeg...")
    assemble_video(png_paths, wav_paths, video_dir, OUT_MP4, "mini_fluid")
    logger.info("=" * 60)
    logger.info("SUCCESS! Fluid Vision Mini Test MP4 created at: %s", OUT_MP4)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
