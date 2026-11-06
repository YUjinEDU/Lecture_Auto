import argparse
import glob
import json
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = "/home/dbsdosdb/workspace/Lecture_Auto"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import soundfile as sf  # noqa: E402
import torch  # noqa: E402

from lecture_auto.pipeline import raon_tts as R  # noqa: E402
from lecture_auto.pipeline.pronunciation import load_pronunciation_entries  # noqa: E402

DIRS = [
    "data/work_batch/10_종합설계_07_시스템구조_자유분량",
    "data/work_batch/11_종합설계_07_시스템구조_30분이상",
]
REF = "data/audio_ref/candidates_s24/ref_390.wav"
SEEDS = (17, 29, 43, 61)
OUT = f"{ROOT}/data/audio_ref/comparison_s24/bon"


def sentences(count):
    segs = []
    for d in DIRS:
        for f in sorted(glob.glob(f"{d}/audio/slide_*.wav.qc.json")):
            for s in json.load(open(f, encoding="utf-8")).get("segments") or []:
                if len(s.get("text") or "") >= 40:
                    segs.append(s["text"])
    step = len(segs) / count
    return [segs[int(i * step) + 1] for i in range(count)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", required=True)
    ap.add_argument("--count", type=int, default=24)
    a = ap.parse_args()
    k, n = (int(x) for x in a.shard.split("/"))
    os.makedirs(OUT, exist_ok=True)
    texts = sentences(a.count)
    entries = load_pronunciation_entries(Path("config/pronunciation.yaml"))
    pipe = R.load_raon_pipeline(device="cuda:0")
    rows = []
    for i, text in enumerate(texts):
        if i % n != k:
            continue
        expected = max(len(text) / R._CHARS_PER_SECOND, 3.0)
        cap = int(min(max(math.ceil(expected * R._CODEC_FRAME_RATE * R._TOKEN_CAP_RATIO) + 8, R._MIN_MAX_NEW_TOKENS), R._MAX_MAX_NEW_TOKENS))
        pipe.task_params["tts"]["max_new_tokens"] = cap
        for seed in SEEDS:
            torch.manual_seed(seed)
            wav, sr = pipe.tts(text, speaker_audio=REF)
            trimmed = R._loudness_normalize(R._trim_lead_tail_silence(R._to_numpy(wav, sr), sr), sr)
            reasons = R._gate_reasons(trimmed, sr, expected)
            cer = None
            status = None
            if not reasons:
                with tempfile.NamedTemporaryFile(suffix=".wav") as tmpf:
                    sf.write(tmpf.name, trimmed, sr)
                    check = R.evaluate_transcription(pipe, tmpf.name, text, entries)
                status, cer = check.status, check.cer
            ok = (not reasons) and status == "pass" and cer is not None and cer <= R._MAX_SEGMENT_CER
            sf.write(f"{OUT}/{i:02d}_{seed}.wav", trimmed, sr)
            row = {"i": i, "seed": seed, "chars": len(text), "ok": bool(ok), "reasons": reasons, "stt": status, "cer": cer}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    json.dump({"texts": texts, "rows": rows}, open(f"{OUT}/rows_{k}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
