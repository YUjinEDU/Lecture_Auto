"""S22: Benchmark script comparing baseline script vs K-ToBI restyled script prosody and acoustics.

Measures:
1. Script text metrics: ending ratios (해요체, 하십시오체, 확인/의문형), comma density (AP breathing).
2. Acoustic F0 pitch dynamics: Mean F0, F0 std dev (sigma_F0), pitch range (Hz).
3. Audio mastering with ambient room tone dither (-58 dBFS).
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal

from lecture_auto.pipeline.audio_mastering import master_lecture_speech
from lecture_auto.pipeline.restyle import compute_metrics

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = ROOT / "data" / "audio_ref" / "comparison_s22"

# Real lecture script pairs for comparison
BENCH_PAIRS = [
    {
        "slide_num": 1,
        "name": "slide_01_intro",
        "title": "도입부: 디자인 씽킹과 페르소나",
        "legacy_script": (
            "이 슬라이드는 디자인 씽킹에서 사용자 페르소나의 개념을 설명합니다. "
            "페르소나는 실제 사용자 데이터를 기반으로 만들어진 가상의 인물입니다. "
            "우리는 페르소나를 통하여 사용자의 핵심 문제에 접근할 수 있습니다. "
            "이번 강의에서는 페르소나의 정의와 제작 절차를 상세히 살펴봅니다."
        ),
        "ktobi_script": (
            "자, 이번 시간에는 디자인 씽킹에서 가장 중요한 페르소나를 살펴볼 건데요, "
            "페르소나는 실제 사용자 인터뷰를 바탕으로 만든 가상의 인물인 거죠. "
            "우리가 페르소나를 통해 문제의 본질에 접근할 수 있는데, 왜 그럴까요? "
            "그 구체적인 정의와 제작 과정을 지금부터 하나씩 짚어보겠습니다."
        ),
    },
    {
        "slide_num": 2,
        "name": "slide_02_concept",
        "title": "개념: 페르소나의 세부 구성 요소",
        "legacy_script": (
            "페르소나를 정의할 때는 사용자의 인적 사항과 동기를 포함해야 합니다. "
            "이름, 나이, 직업, 라이프스타일 등이 주요 항목으로 구성됩니다. "
            "또한 인물이 느끼는 구체적인 불편함인 페인 포인트를 반드시 도출합니다. "
            "이러한 요소들이 유기적으로 결합되어 완성도 높은 프로필이 완성됩니다."
        ),
        "ktobi_script": (
            "자, 그러면 페르소나를 만들 때 무엇이 꼭 들어가야 할까요? "
            "이름이나 나이 같은 기본 배경 정보뿐만 아니라, 사용자의 행동 동기가 핵심이죠. "
            "특히 이 인물이 겪는 진짜 불편함, 즉 페인 포인트를 정확히 짚어내야 하는데요, "
            "이런 요소들이 생생하게 결합될 때 비로소 살아있는 프로필이 완성됩니다."
        ),
    },
]


def estimate_f0_contour(wav: np.ndarray, sr: int = 24000, frame_ms: float = 30.0, hop_ms: float = 10.0) -> np.ndarray:
    """Lightweight autocorrelation-based F0 pitch estimator (male voice range 70-350 Hz)."""
    if wav.ndim > 1:
        wav = np.mean(wav, axis=1)

    frame_len = int(sr * frame_ms / 1000.0)
    hop_len = int(sr * hop_ms / 1000.0)
    min_lag = int(sr / 350.0)
    max_lag = int(sr / 70.0)

    f0_list = []
    n_frames = (len(wav) - frame_len) // hop_len
    if n_frames <= 0:
        return np.array([])

    for i in range(n_frames):
        start = i * hop_len
        frame = wav[start : start + frame_len]
        energy = np.mean(frame**2)
        if energy < 1e-4:
            continue

        # Windowing
        windowed = frame * np.hanning(len(frame))
        # Autocorrelation
        corr = signal.correlate(windowed, windowed, mode="full")
        corr = corr[len(corr) // 2 :]

        if max_lag < len(corr):
            lag_peak = min_lag + np.argmax(corr[min_lag:max_lag])
            peak_val = corr[lag_peak]
            if peak_val > 0.3 * corr[0]:  # Voiced threshold
                f0 = sr / lag_peak
                f0_list.append(f0)

    return np.array(f0_list)


def run_benchmark(synth_audio: bool = False, device: str = "cuda:0") -> dict:
    out_dir = DEFAULT_OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    results = []

    pipe = None
    if synth_audio:
        try:
            from lecture_auto.pipeline.raon_tts import load_raon_pipeline
            logger.info("Loading Raon-Speech-9B model on %s...", device)
            pipe = load_raon_pipeline(device=device)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not load Raon model on GPU (%s). Running text metric analysis only.", e)

    ref_voice_path = ROOT / "data" / "audio_ref" / "reference_v2.wav"
    if not ref_voice_path.exists():
        ref_voice_path = ROOT / "data" / "audio_ref" / "reference_v1.wav"

    sr = 24000

    for pair in BENCH_PAIRS:
        s_num = pair["slide_num"]
        name = pair["name"]
        logger.info("Analyzing %s: %s", name, pair["title"])

        m_legacy = compute_metrics(pair["legacy_script"])
        m_ktobi = compute_metrics(pair["ktobi_script"])

        res_item = {
            "slide_num": s_num,
            "name": name,
            "title": pair["title"],
            "legacy_script": pair["legacy_script"],
            "ktobi_script": pair["ktobi_script"],
            "text_metrics": {
                "legacy": m_legacy,
                "ktobi": m_ktobi,
            },
        }

        if pipe is not None and ref_voice_path.exists():
            from lecture_auto.pipeline.raon_tts import synthesize_raon_slide

            # 1. Synthesize legacy
            raw_legacy_path = out_dir / f"{name}_legacy_raw.wav"
            synthesize_raon_slide(
                pipe=pipe,
                text=pair["legacy_script"],
                output_path=raw_legacy_path,
                speaker_audio=ref_voice_path,
            )
            wav_legacy_raw, _ = sf.read(str(raw_legacy_path))
            # Master legacy
            wav_legacy = master_lecture_speech(wav_legacy_raw, sr=sr, dither_room_tone=True)
            path_legacy = out_dir / f"{name}_legacy.wav"
            sf.write(str(path_legacy), wav_legacy, sr)

            # 2. Synthesize K-ToBI
            raw_ktobi_path = out_dir / f"{name}_ktobi_raw.wav"
            synthesize_raon_slide(
                pipe=pipe,
                text=pair["ktobi_script"],
                output_path=raw_ktobi_path,
                speaker_audio=ref_voice_path,
            )
            wav_ktobi_raw, _ = sf.read(str(raw_ktobi_path))
            # Master K-ToBI
            wav_ktobi = master_lecture_speech(wav_ktobi_raw, sr=sr, dither_room_tone=True)
            path_ktobi = out_dir / f"{name}_ktobi_prosody.wav"
            sf.write(str(path_ktobi), wav_ktobi, sr)

            # Analyze F0
            f0_legacy = estimate_f0_contour(wav_legacy, sr=sr)
            f0_ktobi = estimate_f0_contour(wav_ktobi, sr=sr)

            res_item["acoustic_metrics"] = {
                "legacy": {
                    "duration_s": round(len(wav_legacy) / sr, 2),
                    "f0_mean_hz": round(float(np.mean(f0_legacy)), 1) if len(f0_legacy) > 0 else 0.0,
                    "f0_std_hz": round(float(np.std(f0_legacy)), 1) if len(f0_legacy) > 0 else 0.0,
                    "f0_range_hz": round(float(np.max(f0_legacy) - np.min(f0_legacy)), 1) if len(f0_legacy) > 0 else 0.0,
                    "wav_file": str(path_legacy),
                },
                "ktobi": {
                    "duration_s": round(len(wav_ktobi) / sr, 2),
                    "f0_mean_hz": round(float(np.mean(f0_ktobi)), 1) if len(f0_ktobi) > 0 else 0.0,
                    "f0_std_hz": round(float(np.std(f0_ktobi)), 1) if len(f0_ktobi) > 0 else 0.0,
                    "f0_range_hz": round(float(np.max(f0_ktobi) - np.min(f0_ktobi)), 1) if len(f0_ktobi) > 0 else 0.0,
                    "wav_file": str(path_ktobi),
                },
            }

        results.append(res_item)

    report_path = out_dir / "bench_prosody_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Saved benchmark report to %s", report_path)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark S22 prosody and conversational style")
    parser.add_argument("--synth-audio", action="store_true", help="Generate real audio using Raon-Speech-9B on GPU")
    parser.add_argument("--device", default="cuda:0", help="CUDA device (e.g. cuda:0)")
    args = parser.parse_args()

    results = run_benchmark(synth_audio=args.synth_audio, device=args.device)
    print("\n=== S22 PROSODY BENCHMARK RESULTS ===")
    for item in results:
        print(f"\n[{item['name']}: {item['title']}]")
        print("  Legacy Text Metrics:", item["text_metrics"]["legacy"])
        print("  K-ToBI Text Metrics:", item["text_metrics"]["ktobi"])
        if "acoustic_metrics" in item:
            print("  Legacy Acoustic F0:", item["acoustic_metrics"]["legacy"])
            print("  K-ToBI Acoustic F0:", item["acoustic_metrics"]["ktobi"])


if __name__ == "__main__":
    main()
