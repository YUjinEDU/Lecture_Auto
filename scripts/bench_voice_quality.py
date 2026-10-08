"""A/B Benchmark script to compare voice quality: Legacy (v1) vs Studio Clean (v2) (S21).

Generates side-by-side audio clips using:
- Condition A (Legacy): reference_v1.wav + raw Raon synthesis
- Condition B (S21 Studio): reference_v2.wav (denoised & de-reverbed) + audio mastering chain

Usage:
    uv run python scripts/bench_voice_quality.py --gpu 0
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import soundfile as sf

from lecture_auto.pipeline.audio_mastering import (
    master_lecture_speech,
    trim_speech_tail,
)
from lecture_auto.pipeline.raon_tts import load_raon_pipeline, synthesize_raon_slide

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Representative test sentences reflecting actual lecture content (technical terms, endings)
BENCHMARK_SENTENCES = [
    (
        "slide_01_intro",
        "자, 안녕하세요. 그럼 지금부터 2026년도 디자인 씽킹과 사용자 경험 분석 강의를 시작하겠습니다.",
        8.0,
    ),
    (
        "slide_02_concept",
        "여기서 핵심은 사용자의 잠재적 니즈를 파악하기 위한 심층 인터뷰와 관찰 기법, 바로 쉐도잉을 적용하는 것입니다.",
        10.0,
    ),
]


def run_benchmark(output_dir: Path, device: str = "cuda:0") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    ref_v1 = Path("data/audio_ref/reference_v1.wav")
    ref_v2 = Path("data/audio_ref/reference_v2.wav")

    if not ref_v1.exists():
        raise FileNotFoundError(f"Missing {ref_v1}")
    if not ref_v2.exists():
        raise FileNotFoundError(f"Missing {ref_v2}. Run scripts/build_voice_reference.py first.")

    logger.info("Loading RaonPipeline on %s...", device)
    pipe = load_raon_pipeline(device=device)

    sr = 24000

    for name, text_content, target_sec in BENCHMARK_SENTENCES:
        logger.info("--- Testing '%s' ---", name)
        logger.info("Script: %s", text_content)

        # 1. Condition A: Legacy (v1 reference, raw output)
        logger.info("Synthesizing Condition A (Legacy v1)...")
        raw_v1_path = output_dir / f"{name}_v1_legacy.wav"
        synthesize_raon_slide(
            pipe=pipe,
            text=text_content,
            output_path=raw_v1_path,
            speaker_audio=ref_v1,
            max_seconds=target_sec,
        )
        wav_v1, _ = sf.read(raw_v1_path)
        logger.info("Saved Condition A -> %s (%.2fs)", raw_v1_path, len(wav_v1) / sr)

        # 2. Condition B: S21 Studio Clean (v2 reference + tail-trim + mastering)
        logger.info("Synthesizing Condition B (S21 Studio Clean v2)...")
        raw_v2_path = output_dir / f"{name}_v2_raw.wav"
        synthesize_raon_slide(
            pipe=pipe,
            text=text_content,
            output_path=raw_v2_path,
            speaker_audio=ref_v2,
            max_seconds=target_sec,
        )

        wav_v2_raw, _ = sf.read(raw_v2_path)
        # Apply S21 Tail-trim and Mastering Chain
        wav_v2_trimmed = trim_speech_tail(wav_v2_raw, sr=sr, safety_pad_ms=70.0)
        wav_v2_mastered = master_lecture_speech(wav_v2_trimmed, sr=sr, target_lufs=-20.0)

        out_v2_path = output_dir / f"{name}_v2_studio_mastered.wav"
        sf.write(out_v2_path, wav_v2_mastered, sr)
        raw_v2_path.unlink(missing_ok=True)  # Clean up temporary raw
        logger.info(
            "Saved Condition B -> %s (raw=%.2fs -> trimmed/mastered=%.2fs)",
            out_v2_path,
            len(wav_v2_raw) / sr,
            len(wav_v2_mastered) / sr,
        )

    logger.info("=" * 60)
    logger.info("A/B Benchmark completed! Audio clips saved to: %s", output_dir.resolve())
    logger.info("Listen and compare:")
    logger.info("  - Condition A: *_v1_legacy.wav (original reference, unmastered)")
    logger.info("  - Condition B: *_v2_studio_mastered.wav (denoised reference, de-essed, de-boxed, mastered)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("data/audio_ref/comparison_s21"))
    parser.add_argument("--gpu", type=str, default="cuda:0")
    args = parser.parse_args()

    run_benchmark(output_dir=args.out_dir, device=args.gpu)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
