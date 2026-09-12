"""Re-synthesize a few known-bad slides to check the v6 gate before a full batch.

Lecture 01's worst cases under v5: slide 009 truncated (291 chars -> 26.9s of a
41.6s estimate), slide 046 ran 141.3s against a 60s budget, slide 002 had a
24.6s internal silence. If v6 can't get these through its own gate, a 4-hour
batch run is not worth starting.

    uv run python scripts/smoke_tts_gate.py 9 46 2
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import soundfile as sf

from lecture_auto.pipeline.raon_tts import (
    TTS_MODEL_ID,
    _longest_silence_seconds,
    _voiced_ratio,
    load_raon_pipeline,
    synthesize_raon_slide,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SCRIPTS = Path("data/work_batch/01_AI현업_02_디자인씽킹개요/scripts")
OUT = Path("data/smoke_tts_gate")
REF_VOICE = Path("data/audio_ref/test_variants/ref_phone_norm.wav")


def main() -> int:
    slide_numbers = [int(a) for a in sys.argv[1:]] or [9, 46, 2]
    OUT.mkdir(parents=True, exist_ok=True)

    pipe = load_raon_pipeline(TTS_MODEL_ID, device="cuda:0", dtype="bfloat16")

    rows = []
    for n in slide_numbers:
        data = json.loads((SCRIPTS / f"script_{n:03d}.json").read_text(encoding="utf-8"))
        script, target = data["script"], data["target_seconds"]
        out_wav = OUT / f"slide_{n:03d}.wav"
        _, ok = synthesize_raon_slide(pipe, script, out_wav, speaker_audio=REF_VOICE, max_seconds=target)

        wav, sr = sf.read(str(out_wav))
        rows.append(
            (n, len(script), target, len(wav) / sr, _voiced_ratio(wav, sr), _longest_silence_seconds(wav, sr), ok)
        )

    print(f"\n{'slide':>5} {'chars':>6} {'target':>7} {'actual':>7} {'ratio':>6} {'voiced':>7} {'maxsil':>7}  ok")
    for n, chars, target, actual, voiced, sil, ok in rows:
        print(f"{n:5d} {chars:6d} {target:7.1f} {actual:7.1f} {actual/target:6.2f} {voiced:7.2f} {sil:7.1f}  {ok}")

    passed = sum(1 for r in rows if r[-1])
    print(f"\n{passed}/{len(rows)} passed the v6 gate")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
