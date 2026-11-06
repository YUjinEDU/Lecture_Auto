import glob
import json
import os
import sys

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
import torch
import torchaudio

ROOT = "/home/dbsdosdb/workspace/Lecture_Auto"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from lecture_auto.pipeline.voice_match import BAND_CENTERS_HZ, band_levels_db, split_speech_segments  # noqa: E402

HI = BAND_CENTERS_HZ > 3000
LO = (BAND_CENTERS_HZ > 100) & (BAND_CENTERS_HZ < 1000)
OUT = sys.argv[1]
LECTURES = {
    "10_free": "data/work_batch/10_종합설계_07_시스템구조_자유분량",
    "11_30min": "data/work_batch/11_종합설계_07_시스템구조_30분이상",
    "09_unmatched": "data/work_batch/09_종합설계_06_Product_Backlog",
}


def piece_stats(x, sr):
    if len(x) < sr * 0.8:
        return None
    meter = pyln.Meter(sr)
    lufs = meter.integrated_loudness(x.astype(np.float64))
    if not np.isfinite(lufs):
        return None
    lv = band_levels_db(x.astype(np.float32), sr)
    w16 = torchaudio.functional.resample(torch.from_numpy(x.astype(np.float32)), sr, 16000)
    f0 = torchaudio.functional.detect_pitch_frequency(w16, 16000, frame_time=1e-2, win_length=30, freq_low=70, freq_high=350)
    hop = 160
    n = min(len(f0), len(w16) // hop)
    db = 10 * torch.log10((w16[: n * hop].reshape(n, hop) ** 2).mean(1) + 1e-10)
    voiced = db > (db.max() - 30)
    f = f0[:n][voiced][(f0[:n][voiced] > 70) & (f0[:n][voiced] < 350)].numpy()
    if len(f) < 20 or lv is None:
        return None
    return {
        "lufs": float(lufs),
        "f0_st": float(12 * np.log2(np.median(f) / 117.6)),
        "tilt": float(lv[HI].mean() - lv[LO].mean()),
        "dur": len(x) / sr,
    }


def pieces_of(wav, sr, slide_id):
    out = []
    for a, b in split_speech_segments(wav, sr, min_pause_s=0.15, min_len_s=1.5):
        s = piece_stats(wav[a:b], sr)
        if s:
            s["slide"] = slide_id
            out.append(s)
    return out


def summarize(pieces):
    def jumps(key, same_slide):
        return [abs(b[key] - a[key]) for a, b in zip(pieces, pieces[1:]) if (a["slide"] == b["slide"]) == same_slide]

    res = {"n_pieces": len(pieces)}
    for key in ("lufs", "f0_st", "tilt"):
        vals = [p[key] for p in pieces]
        within, across = jumps(key, True), jumps(key, False)
        res[key] = {
            "sd": round(float(np.std(vals)), 2),
            "within_slide_jump_median": round(float(np.median(within)), 2) if within else None,
            "within_slide_jump_p90": round(float(np.percentile(within, 90)), 2) if within else None,
            "slide_boundary_jump_median": round(float(np.median(across)), 2) if across else None,
            "slide_boundary_jump_p90": round(float(np.percentile(across, 90)), 2) if across else None,
        }
    return res


report = {}
for name, d in LECTURES.items():
    pieces = []
    for f in sorted(glob.glob(f"{d}/audio/slide_*.wav")):
        if f.endswith((".cand.wav", ".prev.wav")):
            continue
        wav, sr = sf.read(f)
        wav = wav if wav.ndim == 1 else wav[:, 0]
        pieces += pieces_of(wav, sr, os.path.basename(f))
    report[name] = summarize(pieces)
    print(name, json.dumps(report[name], ensure_ascii=False), flush=True)

real, rsr = sf.read(f"{ROOT}/data/audio_ref/professor_past_lecture_2025.wav")
real = real if real.ndim == 1 else real[:, 0]
chunk = 60 * rsr
pieces = []
for ci, start in enumerate(range(0, min(len(real), 20 * 60 * rsr), chunk)):
    pieces += pieces_of(real[start: start + chunk], rsr, f"real_{ci}")
report["real_professor_20min"] = summarize(pieces)
print("real_professor_20min", json.dumps(report["real_professor_20min"], ensure_ascii=False), flush=True)
json.dump(report, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
