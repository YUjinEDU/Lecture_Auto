"""Stage 1 refactor guard: dump what the production code decides for every lecture.

Run it against the real data before and after each refactor step and diff the two JSON
files; any difference is a behavior change. It only reads: lecture list, per-slide TTS
cache keys and validity, ``--status`` numbers and output paths.

    .venv/bin/python scripts/stage1_baseline.py --data-root ../Lecture_Auto --out before.json

``--data-root`` is the checkout whose ``data/``, ``output/`` and ``config/`` are read;
the code imported is this file's checkout.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REF_VOICE = Path("data/audio_ref/reference_v1.wav")


def snapshot() -> dict:
    from lecture_auto.pipeline.cache import is_cache_valid
    from lecture_auto.production import batch as bgl

    entries = bgl.load_pronunciation_entries(Path("config/pronunciation.yaml"))
    base_work, output_dir = Path("data/work_batch"), Path("output")
    lectures = {}
    for item in bgl.LECTURES:
        lec_id = item["id"]
        ref = Path(item.get("ref_voice") or DEFAULT_REF_VOICE)
        ref_bytes = ref.read_bytes() if ref.exists() else b""
        scripts_dir = base_work / lec_id / "scripts"
        audio_dir = base_work / lec_id / "audio"
        slides = {}
        for path in sorted(scripts_dir.glob("script_[0-9][0-9][0-9].json")) if scripts_dir.is_dir() else []:
            n = int(path.stem.removeprefix("script_"))
            sc = json.loads(path.read_text(encoding="utf-8"))
            key = bgl._tts_cache_key(sc.get("script", ""), ref_bytes, sc.get("target_seconds"), entries)
            slides[str(n)] = {"key": key, "valid": is_cache_valid(audio_dir / f"slide_{n:03d}.wav", key)}
        st = bgl.compute_lecture_status(item, base_work, output_dir)
        lectures[lec_id] = {
            "item": {k: str(v) for k, v in sorted(item.items())},
            "ref_voice": str(ref),
            "output_mp4": str(bgl._lecture_output_mp4(lec_id, output_dir)),
            "status": {k: str(v) for k, v in vars(st).items()},
            "slides": slides,
        }
    return {"order": [item["id"] for item in bgl.LECTURES], "lectures": lectures}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    os.environ.pop("LECTURE_AUTO_REF_VOICE", None)
    sys.path.insert(0, str(CODE_ROOT))
    os.chdir(args.data_root)
    data = snapshot()
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    n_slides = sum(len(v["slides"]) for v in data["lectures"].values())
    print(f"{len(data['order'])} lectures, {n_slides} slides -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
