"""Build the fixed spectral target used by voice_match from finished lectures.

    python scripts/build_voice_target.py --lectures 06_... 07_... --out config/voice_target.json

Reads the final slide WAVs only (CPU, no models), splits them into segments on the
exact-zero pauses, and writes the median level-independent 1/3-octave profile.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lecture_auto.pipeline.voice_match import (
    BAND_CENTERS_HZ,
    band_levels_db,
    split_speech_segments,
)


def segment_profiles(lecture_ids: list[str], work_root: Path) -> np.ndarray:
    rows = []
    for lec in lecture_ids:
        for path in sorted(glob.glob(str(work_root / lec / "audio" / "slide_*.wav"))):
            wav, sr = sf.read(path)
            wav = wav if wav.ndim == 1 else wav[:, 0]
            for a, b in split_speech_segments(wav, sr):
                levels = band_levels_db(wav[a:b].astype(np.float32), sr)
                if levels is not None:
                    rows.append(levels - levels.mean())
    return np.stack(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lectures", nargs="+", required=True, help="lecture ids under data/work_batch")
    ap.add_argument("--out", type=Path, default=ROOT / "config" / "voice_target.json")
    ap.add_argument("--work-root", type=Path, default=ROOT / "data" / "work_batch")
    args = ap.parse_args(argv)

    profiles = segment_profiles(args.lectures, args.work_root)
    target = np.median(profiles, axis=0)
    out = {
        "band_centers_hz": [round(float(c), 1) for c in BAND_CENTERS_HZ],
        "profile_db": [round(float(v), 2) for v in target],
        "band_sd_db": [round(float(v), 2) for v in profiles.std(axis=0)],
        "segments": len(profiles),
        "lectures": args.lectures,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(profiles)} segments from {len(args.lectures)} lectures -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
