import json
import sys

import numpy as np
import soundfile as sf

sys.argv = ["x", "/dev/null"]
ns = {}
exec(compile(open("/tmp/voice_measure/baseline3.py").read().split("\nreport = {}")[0], "b3", "exec"), ns)
piece_stats, CMP = ns["piece_stats"], ns["CMP"]
BON = f"{CMP}/bon"
SEEDS = (17, 29, 43, 61)
KEYS = ("active_db", "f0_st", "tilt")

rows = []
for k in (0, 1):
    rows += json.load(open(f"{BON}/rows_{k}.json", encoding="utf-8"))["rows"]
by = {}
for r in rows:
    by.setdefault(r["i"], {})[r["seed"]] = r

feats = {}
for i, cands in by.items():
    for seed, r in cands.items():
        w, sr = sf.read(f"{BON}/{i:02d}_{seed}.wav")
        w = (w if w.ndim == 1 else w[:, 0]).astype(np.float32)
        s = piece_stats(w, sr)
        if s:
            feats[(i, seed)] = s

usable = sorted(i for i, c in by.items() if any(c[s]["ok"] and (i, s) in feats for s in c))
n_cands = [sum(1 for s in by[i] if by[i][s]["ok"] and (i, s) in feats) for i in usable]
print(f"sentences={len(by)} usable={len(usable)} ok candidates per usable sentence: mean {np.mean(n_cands):.2f} min {min(n_cands)} max {max(n_cands)}")
print(f"gate pass rate per attempt: {np.mean([r['ok'] for r in rows]):.2f}; first-seed(17) pass rate: {np.mean([by[i][17]['ok'] for i in by]):.2f}")

allv = {k: np.array([feats[(i, s)][k] for (i, s) in feats if by[i][s]["ok"]]) for k in KEYS}
scale = {k: float(1.4826 * np.median(np.abs(allv[k] - np.median(allv[k]))) + 1e-6) for k in KEYS}


def first_ok(i):
    for s in SEEDS:
        if s in by[i] and by[i][s]["ok"] and (i, s) in feats:
            return s
    return None


def policy_first():
    return {i: first_ok(i) for i in usable}


def policy_running():
    chosen, hist = {}, {k: [] for k in KEYS}
    for i in usable:
        cands = [s for s in SEEDS if s in by[i] and by[i][s]["ok"] and (i, s) in feats]
        if not hist["active_db"]:
            pick = first_ok(i)
        else:
            med = {k: float(np.median(hist[k])) for k in KEYS}
            pick = min(cands, key=lambda s: sum(abs(feats[(i, s)][k] - med[k]) / scale[k] for k in KEYS))
        chosen[i] = pick
        for k in KEYS:
            hist[k].append(feats[(i, pick)][k])
    return chosen


def report(name, chosen):
    seq = [feats[(i, chosen[i])] for i in usable]
    out = {"policy": name, "n": len(seq)}
    for k in KEYS:
        v = [p[k] for p in seq]
        jumps = [abs(b - a) for a, b in zip(v, v[1:])]
        out[k] = f"sd {np.std(v):.2f} adj_med {np.median(jumps):.2f} adj_p90 {np.percentile(jumps, 90):.2f}"
    out["f0_range_mean"] = round(float(np.mean([p["f0_range"] for p in seq])), 2)
    out["intra_loud_sd_mean"] = round(float(np.mean([p["intra_sd"] for p in seq])), 2)
    return out, chosen


base, c0 = report("first passing seed (current)", policy_first())
run, c1 = report("closest to running median", policy_running())
for r in (base, run):
    print(json.dumps(r, ensure_ascii=False))
print("sentences where the pick differs:", sum(c0[i] != c1[i] for i in usable), "of", len(usable))

spread = {k: [] for k in KEYS}
for i in usable:
    ok = [feats[(i, s)] for s in SEEDS if s in by[i] and by[i][s]["ok"] and (i, s) in feats]
    if len(ok) >= 2:
        for k in KEYS:
            spread[k].append(max(p[k] for p in ok) - min(p[k] for p in ok))
print("within-sentence seed spread (max-min over ok seeds), mean:", {k: round(float(np.mean(v)), 2) for k, v in spread.items()})
print("between-sentence sd (all ok candidates):", {k: round(float(np.std(allv[k])), 2) for k in KEYS})

for name, chosen in (("first", c0), ("running", c1)):
    parts, sr_out = [], None
    for i in usable:
        w, sr_out = sf.read(f"{BON}/{i:02d}_{chosen[i]}.wav")
        w = w if w.ndim == 1 else w[:, 0]
        parts += [w.astype(np.float32), np.zeros(int(0.5 * sr_out), dtype=np.float32)]
    sf.write(f"{CMP}/listen_bon_{name}.wav", np.concatenate(parts), sr_out)
print("wrote listen_bon_first.wav, listen_bon_running.wav")
