"""S17-c: one-command production run.

    python scripts/produce.py --only 7,8,9 --gpus 0,1 [--workers-per-gpu 1] [--slides ..]
        [--no-stt] [--max-restarts 2] [--fix-failed] [--dry-run]

Launches GPUs x workers-per-gpu ``batch_generate_lectures.py --claim <run_id>``
workers (dynamic per-slide claim), restarts a worker that exits non-zero (up to
--max-restarts), then assembles each lecture once (``--assemble-only``) and
prints the status table. Exit 1 if any worker gave up, any assembly failed or
any lecture is not a final video.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lecture_auto.production.batch import (  # noqa: E402
    EXIT_NO_RETRY,
    LECTURES,
    _format_status_line,
    _select_lectures,
    compute_lecture_status,
)

LOG_ROOT = ROOT / "logs"
# Measured: a Raon worker peaks at 18.5 GB; two on one A6000 ran 1.63x faster end to end.
_VRAM_PER_WORKER_MIB = 20 * 1024
_BATCH = [sys.executable, "-m", "scripts.batch_generate_lectures"]


def _free_vram_mib(runner=subprocess.run) -> dict[str, int]:
    """GPU index -> free VRAM in MiB; empty when nvidia-smi is unavailable."""
    try:
        out = runner(
            ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return {}
    return {i.strip(): int(f) for i, f in (line.split(",") for line in out.splitlines() if line.strip())}


def workers_per_gpu(gpus: list[str], requested: int | None, free: dict[str, int]) -> dict[str, int]:
    """Workers to start per GPU: the requested count, else 2 where two fit in free VRAM."""
    if requested is not None:
        return dict.fromkeys(gpus, requested)
    return {g: 2 if free.get(g, 0) >= 2 * _VRAM_PER_WORKER_MIB else 1 for g in gpus}


def _err(msg: str):
    raise SystemExit(f"produce.py: {msg}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", required=True)
    ap.add_argument("--gpus", required=True, help="comma-separated CUDA indexes, e.g. 0,1")
    ap.add_argument(
        "--workers-per-gpu", type=int, default=None,
        help="default: 2 on a GPU with >= 40 GiB free VRAM, else 1 (GPU indexes follow nvidia-smi)",
    )
    ap.add_argument("--slides", default=None)
    ap.add_argument("--no-stt", action="store_true")
    ap.add_argument("--max-restarts", type=int, default=2)
    ap.add_argument("--fix-failed", action="store_true")
    ap.add_argument(
        "--heal", action="store_true",
        help="after assembly, retry held-back slides of every non-final lecture once (batch --heal)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    selected = _select_lectures(args.only, _err)
    run_id = time.strftime("%Y%m%d_%H%M%S")
    base = list(_BATCH)
    common = ["--only", args.only, "--claim", run_id]
    for flag, on in (("--no-stt", args.no_stt), ("--fix-failed", args.fix_failed)):
        if on:
            common.append(flag)
    if args.slides:
        common += ["--slides", args.slides]

    gpus = [x.strip() for x in args.gpus.split(",")]
    per_gpu = workers_per_gpu(gpus, args.workers_per_gpu, _free_vram_mib())
    print(f"workers per gpu: {per_gpu}")
    workers = [(g, k, base + common + ["--gpu", g]) for g in gpus for k in range(per_gpu[g])]
    assembles = [
        base + ["--only", lec["id"], "--assemble-only"] for lec in selected
    ]

    first_gpu = args.gpus.split(",")[0].strip()
    heals = [
        base + ["--only", lec["id"], "--heal", "--gpu", first_gpu] for lec in selected
    ] if args.heal else []

    if args.dry_run:
        for _, _, cmd in workers:
            print(" ".join(cmd))
        for cmd in assembles:
            print(" ".join(cmd))
        for cmd in heals:
            print(" ".join(cmd))
        return 0

    log_dir = LOG_ROOT / f"produce_{run_id}"
    log_dir.mkdir(parents=True, exist_ok=True)
    failed = False

    def launch(g, k, cmd):
        with (log_dir / f"worker_{g}_{k}.log").open("ab") as log:
            return subprocess.Popen(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)

    live = []  # [proc, g, k, cmd, restarts]
    for i, (g, k, cmd) in enumerate(workers):
        if i:
            time.sleep(20)  # stagger model loads
        live.append([launch(g, k, cmd), g, k, cmd, 0])
    while live:
        for w in list(live):
            rc = w[0].poll()
            if rc is None:
                continue
            if rc == EXIT_NO_RETRY:
                print(f"WARNING: worker gpu{w[1]}#{w[2]} hit a precondition error (see its log); not restarting")
                failed = True
                live.remove(w)
                continue
            if rc != 0 and w[4] < args.max_restarts:
                w[4] += 1
                print(f"worker gpu{w[1]}#{w[2]} exited {rc}; restart {w[4]}/{args.max_restarts}")
                w[0] = launch(w[1], w[2], w[3])
                continue
            if rc != 0:
                print(f"WARNING: worker gpu{w[1]}#{w[2]} exited {rc}; gave up after {w[4]} restarts")
                failed = True
            live.remove(w)
        if live:
            time.sleep(5)

    for cmd in assembles:
        if subprocess.run(cmd, cwd=ROOT).returncode != 0:
            print("WARNING: assemble failed:", " ".join(cmd))
            failed = True

    for lec, cmd in zip(selected, heals):
        if compute_lecture_status(lec, ROOT / "data" / "work_batch", ROOT / "output").video_state == "final":
            continue
        if subprocess.run(cmd, cwd=ROOT, check=False).returncode != 0:
            print("WARNING: heal failed:", " ".join(cmd))
            failed = True

    for lec in selected:
        st = compute_lecture_status(lec, ROOT / "data" / "work_batch", ROOT / "output")
        print(_format_status_line(LECTURES.index(lec) + 1, lec["id"], st))
        failed |= st.video_state != "final"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
