import sys

import numpy as np
import pyloudnorm as pyln

sys.argv = ["x", "/dev/null"]
ns = {}
exec(compile(open("/tmp/voice_measure/baseline3.py").read().split("\nreport = {}")[0], "b3", "exec"), ns)
split_by_energy, read_mono, CMP = ns["split_by_energy"], ns["read_mono"], ns["CMP"]


def stats(path):
    wav, sr = read_mono(path)
    meter = pyln.Meter(sr)
    pieces = split_by_energy(wav, sr)
    lufs = [meter.integrated_loudness(wav[a:b].astype(np.float64)) for a, b in pieces]
    # short-term loudness: 3 s sliding window over speech-only samples (pause removed), 1 s hop
    sp = np.concatenate([wav[a:b] for a, b in pieces])
    win, hop = 3 * sr, sr
    st = [meter.integrated_loudness(sp[i: i + win].astype(np.float64)) for i in range(0, len(sp) - win, hop)]
    st = [x for x in st if np.isfinite(x)]
    j = [abs(b - a) for a, b in zip(lufs, lufs[1:])]
    return len(pieces), np.std(lufs), np.median(j), np.percentile(j, 90), np.std(st), np.percentile(st, 95) - np.percentile(st, 10)


print("file                      n  piece_LUFS_sd  adj_med  adj_p90  LUFS-S_sd  LUFS-S_p95-p10")
for ref in ("v2", "r216", "r390"):
    for tag, name in (("raw gate-ok", f"listen_ok_{ref}.wav"), ("prod post", f"listen_prod_{ref}.wav"), ("prod+lev1.0", f"listen_lev10_{ref}.wav"), ("prod+lev0.6", f"listen_lev06_{ref}.wav")):
        n, sd, am, ap, ssd, rng = stats(f"{CMP}/{name}")
        print(f"{ref:5s} {tag:12s} {n:3d}   {sd:6.2f}      {am:6.2f}  {ap:6.2f}   {ssd:6.2f}     {rng:6.2f}")
