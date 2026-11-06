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
from lecture_auto.pipeline.voice_match import (  # noqa: E402
    BAND_CENTERS_HZ,
    band_levels_db,
    load_voice_target,
    match_segment_spectra,
    split_speech_segments,
)

HI = BAND_CENTERS_HZ > 3000
LO = (BAND_CENTERS_HZ > 100) & (BAND_CENTERS_HZ < 1000)
OUT = sys.argv[1]
CMP = f"{ROOT}/data/audio_ref/comparison_s24"
FR = 0.05


def split_by_energy(x, sr, min_pause_s=0.15, min_len_s=1.5, rel_db=-30.0):
    n = int(sr * FR)
    k = len(x) // n
    e = np.sqrt((x[: k * n].reshape(k, n) ** 2).mean(1) + 1e-12)
    db = 20 * np.log10(e)
    sil = db < (np.percentile(db, 95) + rel_db)
    pieces, start, run = [], None, 0
    for i, s in enumerate(sil):
        if not s:
            if start is None:
                start = i
            run = 0
        elif start is not None:
            run += 1
            if run * FR >= min_pause_s:
                end = i - run + 1
                if (end - start) * FR >= min_len_s:
                    pieces.append((start * n, end * n))
                start, run = None, 0
    if start is not None and (k - start) * FR >= min_len_s:
        pieces.append((start * n, k * n))
    return pieces


def block_db(x, sr):
    blk = int(sr * 0.4)
    k = len(x) // blk
    if k < 3:
        return None
    return 20 * np.log10(np.sqrt((x[: k * blk].reshape(k, blk) ** 2).mean(1)) + 1e-9)


def piece_stats(x, sr):
    bd = block_db(x, sr)
    if bd is None:
        return None
    act = bd[bd > bd.max() - 15]
    lv = band_levels_db(x.astype(np.float32), sr)
    w16 = torchaudio.functional.resample(torch.from_numpy(x.astype(np.float32)), sr, 16000)
    f0 = torchaudio.functional.detect_pitch_frequency(w16, 16000, frame_time=1e-2, win_length=30, freq_low=70, freq_high=350)
    hop = 160
    n = min(len(f0), len(w16) // hop)
    db = 10 * torch.log10((w16[: n * hop].reshape(n, hop) ** 2).mean(1) + 1e-10)
    voiced = db > (db.max() - 30)
    f = f0[:n][voiced][(f0[:n][voiced] > 70) & (f0[:n][voiced] < 350)].numpy()
    if lv is None or len(f) < 20 or len(act) < 2:
        return None
    st = 12 * np.log2(f / np.median(f))
    return {
        "active_db": float(np.median(act)),
        "intra_sd": float(np.std(act)),
        "f0_st": float(12 * np.log2(np.median(f) / 117.6)),
        "f0_range": float(np.percentile(st, 90) - np.percentile(st, 10)),
        "tilt": float(lv[HI].mean() - lv[LO].mean()),
    }


def pieces_of(wav, sr, tag):
    out = []
    for a, b in split_by_energy(wav, sr):
        s = piece_stats(wav[a:b], sr)
        if s:
            s["slide"] = tag
            out.append(s)
    return out


def summarize(pieces):
    res = {"n": len(pieces)}
    for key in ("active_db", "f0_st", "tilt"):
        vals = [p[key] for p in pieces]
        jumps = [abs(b[key] - a[key]) for a, b in zip(pieces, pieces[1:]) if a["slide"] == b["slide"]]
        res[key] = {"sd": round(float(np.std(vals)), 2), "adj_med": round(float(np.median(jumps)), 2), "adj_p90": round(float(np.percentile(jumps, 90)), 2)}
    res["intra_loud_sd_mean"] = round(float(np.mean([p["intra_sd"] for p in pieces])), 2)
    res["f0_range_mean"] = round(float(np.mean([p["f0_range"] for p in pieces])), 2)
    return res


def read_mono(path):
    w, sr = sf.read(path)
    return (w if w.ndim == 1 else w[:, 0]).astype(np.float32), sr


def production_like(wav, sr):
    target = load_voice_target()
    spans = split_speech_segments(wav, sr, min_pause_s=0.15, min_len_s=1.0)
    if not spans:
        return wav
    segs = match_segment_spectra([wav[a:b] for a, b in spans], sr, target)
    gap = np.zeros(int(0.2 * sr), dtype=np.float32)
    joined = np.concatenate([np.concatenate([s, gap]) for s in segs])
    meter = pyln.Meter(sr)
    lufs = meter.integrated_loudness(joined.astype(np.float64))
    return pyln.normalize.loudness(joined.astype(np.float64), lufs, -20.0).astype(np.float32)


report = {}
for ref in ("v2", "r216", "r390"):
    for tag, fname in (("raw_all", f"listen_{ref}.wav"), ("raw_gate_ok", f"listen_ok_{ref}.wav")):
        wav, sr = read_mono(f"{CMP}/{fname}")
        report[f"{ref}:{tag}"] = summarize(pieces_of(wav, sr, "f"))
        print(f"{ref}:{tag}", json.dumps(report[f"{ref}:{tag}"]), flush=True)
    wav, sr = read_mono(f"{CMP}/listen_ok_{ref}.wav")
    proc = production_like(wav, sr)
    sf.write(f"{CMP}/listen_prod_{ref}.wav", proc, sr)
    report[f"{ref}:gate_ok+prod_post"] = summarize(pieces_of(proc, sr, "f"))
    print(f"{ref}:gate_ok+prod_post", json.dumps(report[f"{ref}:gate_ok+prod_post"]), flush=True)

for name, d in (("shipped_10", "data/work_batch/10_종합설계_07_시스템구조_자유분량"), ("shipped_11", "data/work_batch/11_종합설계_07_시스템구조_30분이상")):
    pieces = []
    for f in sorted(glob.glob(f"{ROOT}/{d}/audio/slide_*.wav")):
        if f.endswith((".cand.wav", ".prev.wav")):
            continue
        w, sr = read_mono(f)
        pieces += pieces_of(w, sr, os.path.basename(f))
    report[name] = summarize(pieces)
    print(name, json.dumps(report[name]), flush=True)

real, rsr = read_mono(f"{ROOT}/data/audio_ref/professor_past_lecture_2025.wav")
pieces = []
for ci, start in enumerate(range(0, min(len(real), 25 * 60 * rsr), 120 * rsr)):
    pieces += pieces_of(real[start: start + 120 * rsr], rsr, f"real_{ci}")
report["real_professor"] = summarize(pieces)
print("real_professor", json.dumps(report["real_professor"]), flush=True)
json.dump(report, open(OUT, "w"), indent=1)
