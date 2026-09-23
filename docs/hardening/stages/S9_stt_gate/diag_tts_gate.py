"""Diagnostic: for real 04-1 segments, run ALL planned attempts (no early stop),
save every wav, and record gate metrics + per-clip STT/CER. Read-only on data/.
Usage: RUN from repo root: .venv/bin/python <this> --gpu 0 --slides 8,10 --out <dir>
"""
import argparse, json, glob, math, time
from pathlib import Path
import numpy as np, soundfile as sf, torch

from lecture_auto.pipeline import raon_tts as R

ap = argparse.ArgumentParser()
ap.add_argument("--gpu", type=int, default=0)
ap.add_argument("--slides", default="8,10")
ap.add_argument("--out", required=True)
args = ap.parse_args()
out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
lec = glob.glob("data/work_batch/06_*")[0]
ref = "data/audio_ref/reference_v1.wav"

pipe = R.load_raon_pipeline(R.TTS_MODEL_ID, device=f"cuda:{args.gpu}", dtype="bfloat16")
rows = open(out / "rows.jsonl", "a", encoding="utf-8")

for n in [int(x) for x in args.slides.split(",")]:
    script = json.load(open(f"{lec}/scripts/script_{n:03d}.json"))["script"]
    segs = R.split_into_segments(script)
    prev = None  # (wav_path, text) of previous segment's seed-17 clip, as continuation prefill
    for i, text in enumerate(segs):
        expected = max(len(text) / R._CHARS_PER_SECOND, 3.0)
        min_s = len(text) / R._CHARS_PER_SECOND * R._MIN_DURATION_RATIO
        mnt = int(min(max(math.ceil(expected * R._CODEC_FRAME_RATE * 1.5) + 8, R._MIN_MAX_NEW_TOKENS), R._MAX_MAX_NEW_TOKENS))
        for k in ("tts", "tts_continuation"):
            pipe.task_params[k]["max_new_tokens"] = mnt
        first_clip = None
        for seed, use_cont in R.plan_attempts(prev is not None):
            torch.manual_seed(seed)
            t0 = time.monotonic()
            try:
                if use_cont:
                    a, sr = pipe.tts_continuation(target_text=text, ref_audio=str(prev[0]), ref_text=prev[1], speaker_audio=ref)
                else:
                    a, sr = pipe.tts(text, speaker_audio=ref)
            except Exception as e:  # noqa: BLE001
                rows.write(json.dumps({"slide": n, "seg": i, "seed": seed, "cont": use_cont, "error": repr(e)}, ensure_ascii=False) + "\n"); rows.flush()
                continue
            gen_s = time.monotonic() - t0
            w = R._trim_lead_tail_silence(R._to_numpy(a, sr), sr)
            p = out / f"s{n:03d}_g{i:02d}_seed{seed}_{'c' if use_cont else 'p'}.wav"
            sf.write(str(p), w, sr)
            dur = len(w) / sr
            t1 = time.monotonic()
            chk = R.evaluate_transcription(pipe, p, text)
            row = {
                "slide": n, "seg": i, "chars": len(text), "text": text, "seed": seed, "cont": use_cont,
                "gen_s": round(gen_s, 1), "stt_s": round(time.monotonic() - t1, 1),
                "dur": round(dur, 2), "ratio": round(dur / (len(text) / R._CHARS_PER_SECOND), 3),
                "cps": round(len(text) / dur, 2) if dur else None,
                "voiced": round(R._voiced_ratio(w, sr), 3), "longest_sil": round(R._longest_silence_seconds(w, sr), 2),
                "gate_pass": bool(R._passes_quality_gate(w, sr, expected, min_s)),
                "short": dur < min_s, "long": dur > expected * R._MAX_DURATION_RATIO,
                "stt_status": chk.status, "stt_reasons": chk.reasons, "cer": chk.cer, "transcript": chk.transcript,
                "wav": p.name,
            }
            rows.write(json.dumps(row, ensure_ascii=False) + "\n"); rows.flush()
            if first_clip is None:
                first_clip = (p, text)
        prev = first_clip
print("done")
