"""S18-b: TTS-only throughput bench (no STT). Run only on an idle GPU.

    python scripts/bench_tts_throughput.py --gpu 0 --procs-per-gpu 2 --out bench.json

Refuses to start if another process is on the target GPU (nvidia-smi) unless --force.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import subprocess
import sys
import time

SEED = 17
# 12 fixed Korean sentences, 50-110 chars.
TEXTS = [
    "오늘은 디자인 씽킹의 다섯 단계 가운데 첫 번째인 공감 단계에 대해서 차근차근 살펴보겠습니다.",
    "사용자를 관찰하고 인터뷰하면서 겉으로 드러나지 않는 불편과 숨은 욕구를 찾아내는 것이 핵심입니다.",
    "문제 정의 단계에서는 수집한 관찰 결과를 한 문장으로 정리하여 팀이 같은 방향을 바라보도록 만듭니다.",
    "아이디어 발상 단계에서는 평가를 미루고 가능한 한 많은 아이디어를 자유롭게 쏟아내는 것이 중요합니다.",
    "프로토타입은 완성도가 높을 필요가 없으며, 종이와 테이프만으로도 충분히 아이디어를 검증할 수 있습니다.",
    "테스트 단계에서 얻은 피드백은 다시 앞 단계로 돌아가 문제를 재정의하는 데 활용될 수 있습니다.",
    "이 과정은 한 번에 끝나는 직선이 아니라 여러 번 반복되는 순환 구조라는 점을 반드시 기억해 두시기 바랍니다.",
    "다음 슬라이드에서는 실제 사례를 통해 각 단계가 어떻게 연결되는지 구체적으로 확인해 보겠습니다.",
    "팀 프로젝트에서는 역할을 나누기보다 모든 구성원이 각 단계에 함께 참여하는 방식이 더 효과적입니다.",
    "여기서 말하는 사용자는 서비스를 직접 쓰는 사람뿐 아니라 그 주변의 이해관계자까지 포함합니다.",
    "정리하면, 좋은 문제 정의는 좋은 해결책의 절반이라는 말이 디자인 씽킹에서도 그대로 적용됩니다.",
    "그럼 지금까지 배운 내용을 바탕으로 두세 명씩 짝을 지어 간단한 실습을 진행해 보도록 하겠습니다.",
]


def gpu_busy(gpu: int, runner=subprocess.run) -> list[str]:
    """Return PIDs of compute processes on the GPU (empty list = idle)."""

    def q(*args):
        return runner(["nvidia-smi", *args], capture_output=True, text=True, check=True).stdout

    uuid = q("-i", str(gpu), "--query-gpu=uuid", "--format=csv,noheader").strip()
    rows = q("--query-compute-apps=pid,gpu_uuid", "--format=csv,noheader").splitlines()
    return [r.split(",")[0].strip() for r in rows if r.strip() and r.split(",")[1].strip() == uuid]


def aggregate(results: list[dict], wall_s: float) -> dict:
    gen = sum(r["gen_seconds"] for r in results)
    audio = sum(r["audio_seconds"] for r in results)
    return {
        "procs": results,
        "wall_seconds": round(wall_s, 2),
        "total_audio_seconds": round(audio, 2),
        "total_gen_seconds": round(gen, 2),
        "rtf": round(gen / audio, 3) if audio else None,
        "throughput_audio_per_wall_s": round(audio / wall_s, 3) if wall_s else None,
        "peak_vram_bytes": max((r["peak_vram_bytes"] for r in results), default=0),
    }


def _worker(gpu: int, q) -> None:
    import torch

    from lecture_auto.pipeline.raon_tts import _to_numpy, load_raon_pipeline

    pipe = load_raon_pipeline(device=f"cuda:{gpu}")
    gen = audio = 0.0
    for text in TEXTS:
        torch.manual_seed(SEED)
        t = time.monotonic()
        wav, sr = pipe.tts(text)
        gen += time.monotonic() - t
        audio += len(_to_numpy(wav, sr)) / sr
    q.put({"gen_seconds": gen, "audio_seconds": audio, "rtf": gen / audio if audio else None,
           "peak_vram_bytes": torch.cuda.max_memory_allocated(gpu)})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", type=int, default=0)
    ap.add_argument("--procs-per-gpu", type=int, choices=(1, 2), default=1)
    ap.add_argument("--out", default="bench_tts_throughput.json")
    ap.add_argument("--force", action="store_true", help="run even if other processes use the GPU")
    a = ap.parse_args(argv)
    busy = gpu_busy(a.gpu)
    if busy and not a.force:
        print(f"GPU {a.gpu} is in use by PIDs {busy}; refusing (use --force).", file=sys.stderr)
        return 2
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    t0 = time.monotonic()
    ps = [ctx.Process(target=_worker, args=(a.gpu, q)) for _ in range(a.procs_per_gpu)]
    for p in ps:
        p.start()
    results = [q.get() for _ in ps]
    for p in ps:
        p.join()
    out = aggregate(results, time.monotonic() - t0)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
