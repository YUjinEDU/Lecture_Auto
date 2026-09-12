"""Score every slide wav against the gate and show what each threshold would reject.

The current thresholds were calibrated on v5 output, before the trim function,
the segmentation and the rate constant all changed. This measures the actual v8
distribution so the thresholds can be set from it rather than inherited.

Synthesis is deterministic over fixed seeds, so a slide that would now pass does
not need re-synthesizing -- `--accept` just writes the cache sidecar for it.

    uv run python scripts/recalibrate_gate.py              # report only
    uv run python scripts/recalibrate_gate.py --reconcile   # cache passes, evict failures
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import soundfile as sf

from lecture_auto.pipeline.cache import (
    cache_path_for,
    content_hash,
    is_cache_valid,
    write_cache_hash,
)
from lecture_auto.pipeline.raon_tts import (
    TTS_MODEL_ID,
    TTS_SEEDS,
    TTS_SYNTH_VERSION,
    TTS_TEMPERATURE,
    _longest_silence_seconds,
    _slide_gate_failures,
    _voiced_ratio,
)

LEC = Path("data/work_batch/01_AI현업_02_디자인씽킹개요")
REF_VOICE = Path("data/audio_ref/test_variants/ref_phone_norm.wav")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reconcile", action="store_true",
                    help="cache slides that now pass, evict those that now fail")
    args = ap.parse_args()

    ref_bytes = REF_VOICE.read_bytes() if REF_VOICE.exists() else b""
    rows, accepted, evicted = [], 0, 0

    for wav_path in sorted((LEC / "audio").glob("slide_*.wav")):
        n = int(wav_path.stem.split("_")[1])
        meta = json.loads((LEC / "scripts" / f"script_{n:03d}.json").read_text(encoding="utf-8"))
        script, target = meta["script"], meta["target_seconds"]
        wav, sr = sf.read(str(wav_path))
        dur = len(wav) / sr
        voiced, sil = _voiced_ratio(wav, sr), _longest_silence_seconds(wav, sr)

        reasons = _slide_gate_failures(wav, sr, len(script), target)

        key = content_hash(
            script, ref_bytes, TTS_MODEL_ID, str(TTS_TEMPERATURE), str(TTS_SEEDS), TTS_SYNTH_VERSION
        )
        cached = is_cache_valid(wav_path, key)
        if args.reconcile:
            if not reasons and not cached:
                write_cache_hash(wav_path, key)
                accepted += 1
            elif reasons and cached:
                # Cached under the old segment-only rule, which could not see
                # silence that is only silence relative to the slide's own
                # speech. Evicting is what forces re-synthesis; leaving it would
                # let the next run adopt audio this gate rejects.
                cache_path_for(wav_path).unlink()
                evicted += 1
        rows.append((n, len(script), target, dur, voiced, sil, cached, reasons))

    print(f"\n{'sl':>3} {'chars':>5} {'targ':>6} {'dur':>6} {'voiced':>6} {'maxsil':>6} {'cached':>6}  rejects")
    for n, chars, target, dur, voiced, sil, cached, reasons in rows:
        print(
            f"{n:3d} {chars:5d} {target:6.1f} {dur:6.1f} {voiced:6.2f} {sil:6.1f} "
            f"{cached!s:>6}  {','.join(reasons) or '-'}"
        )

    bad = [r for r in rows if r[-1]]
    print(f"\nslide gate: {len(rows)-len(bad)}/{len(rows)} pass")
    for label, idx, hi in (("voiced", 4, False), ("maxsil", 5, True)):
        vals = sorted((r[idx] for r in rows), reverse=not hi)
        print(f"  {label} deciles: " + " ".join(f"{v:.2f}" for v in vals[:: max(len(vals) // 10, 1)]))
    if args.reconcile:
        print(f"\ncached {accepted} newly-passing slides, evicted {evicted} stale passes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
