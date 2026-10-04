"""S18-b: bench script aggregation + busy-GPU refusal (no GPU, no model)."""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bench", Path(__file__).resolve().parent.parent / "scripts" / "bench_tts_throughput.py"
)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def _runner(apps: str):
    def run(cmd, **kw):
        out = "GPU-aaa\n" if "--query-gpu=uuid" in cmd else apps
        return subprocess.CompletedProcess(cmd, 0, stdout=out)

    return run


def test_texts_fixed_set():
    assert len(bench.TEXTS) == 12 and all(50 <= len(t) <= 110 for t in bench.TEXTS)


def test_gpu_busy_filters_by_uuid():
    assert bench.gpu_busy(0, runner=_runner("123, GPU-aaa\n456, GPU-bbb\n")) == ["123"]
    assert bench.gpu_busy(0, runner=_runner("456, GPU-bbb\n")) == []


def test_main_refuses_when_busy(monkeypatch):
    monkeypatch.setattr(bench, "gpu_busy", lambda gpu: ["123"])

    def boom(*_):
        raise AssertionError("must not spawn")

    monkeypatch.setattr(bench.mp, "get_context", boom)
    assert bench.main(["--out", "unused.json"]) == 2


def test_aggregate():
    rs = [{"gen_seconds": 20.0, "audio_seconds": 10.0, "peak_vram_bytes": 5},
          {"gen_seconds": 30.0, "audio_seconds": 10.0, "peak_vram_bytes": 7}]
    out = bench.aggregate(rs, wall_s=25.0)
    assert out["rtf"] == 2.5 and out["throughput_audio_per_wall_s"] == 0.8 and out["peak_vram_bytes"] == 7
