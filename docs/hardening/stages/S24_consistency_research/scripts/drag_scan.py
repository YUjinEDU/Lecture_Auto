import glob
import json
import os
import sys

import numpy as np
import soundfile as sf
import torch
import torchaudio

ROOT = "/home/dbsdosdb/workspace/Lecture_Auto"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from lecture_auto.pipeline import raon_tts as R  # noqa: E402

OUT = f"{ROOT}/data/audio_ref/comparison_s24"
SRC = f"{ROOT}/data/audio_ref/professor_past_lecture_2025.wav"
MEL = torchaudio.transforms.MelSpectrogram(sample_rate=16000, n_fft=400, hop_length=160, n_mels=40)


def to16(w, sr):
    return torchaudio.functional.resample(torch.from_numpy(np.asarray(w, dtype=np.float32)), sr, 16000)


def mel_track(w16):
    m = MEL(w16)
    lm = torch.log(m + 1e-6)
    d = torch.linalg.norm(lm[:, 1:] - lm[:, :-1], dim=0).numpy()
    db = (10 * torch.log10(m.sum(0) + 1e-9)).numpy()[1:]
    return np.convolve(d, np.ones(5) / 5, mode="same"), db


def longest_run(mask):
    best = cur = 0
    for m in mask:
        cur = cur + 1 if m else 0
        best = max(best, cur)
    return best * 0.01


def silence_runs(wav, sr):
    e = R._frame_energies(wav, sr, 50)
    ref = float(np.percentile(e, 90))
    sil = e < R._RELATIVE_VOICED_THRESHOLD * ref
    runs, cur = [], 0
    for s in sil:
        if s:
            cur += 1
        elif cur:
            runs.append(cur * 0.05)
            cur = 0
    if cur:
        runs.append(cur * 0.05)
    return runs


full, fsr = sf.read(SRC)
full = full if full.ndim == 1 else full[:, 0]
full16 = to16(full, fsr)
real = [mel_track(full16[int(s * 16000): int((s + 9) * 16000)]) for s in np.arange(60, 1900, 45)]
thr = float(np.percentile(np.concatenate([sm[db > db.max() - 30] for sm, db in real]), 20))
real_steady = [longest_run((sm < thr) & (db > db.max() - 30)) for sm, db in real]
print(f"steady thr={thr:.3f} REAL longest steady voiced run p50 {np.percentile(real_steady, 50):.2f}s p90 {np.percentile(real_steady, 90):.2f}s max {max(real_steady):.2f}s")

ok_by = {}
for k in (0, 1):
    for r in json.load(open(f"{OUT}/rows_{k}.json", encoding="utf-8"))["rows"]:
        ok_by[(r["ref"], r["i"])] = r

for ref in ("v2", "r216", "r390"):
    print(f"\n== {ref}")
    print("  clip  gate  reason   longest_sil  steady_run")
    for f in sorted(glob.glob(f"{OUT}/{ref}/*.wav")):
        i = int(os.path.basename(f)[:2])
        w, sr = sf.read(f)
        w = w if w.ndim == 1 else w[:, 0]
        runs = silence_runs(w, sr)
        sm, db = mel_track(to16(w, sr))
        steady = longest_run((sm < thr) & (db > db.max() - 30))
        m = ok_by[(ref, i)]
        print(f"  {i:4d}  {'ok ' if m['ok'] else 'FAIL'}  {str(m['reason']):7s}  {max(runs) if runs else 0:8.2f}   {steady:6.2f}")
