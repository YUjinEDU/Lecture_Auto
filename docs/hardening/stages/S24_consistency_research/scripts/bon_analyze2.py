import sys

import numpy as np

src = open("/tmp/voice_measure/bon_analyze.py").read().split("\nbase, c0 = report(")[0]
ns = {}
exec(compile(src, "bon_analyze", "exec"), ns)
feats, by, usable, SEEDS, KEYS, scale = (ns[k] for k in ("feats", "by", "usable", "SEEDS", "KEYS", "scale"))


def cands(i):
    return [s for s in SEEDS if s in by[i] and by[i][s]["ok"] and (i, s) in feats]


def metrics(chosen):
    seq = [feats[(i, chosen[i])] for i in usable]
    out = {}
    for k in KEYS:
        v = [p[k] for p in seq]
        jumps = [abs(b - a) for a, b in zip(v, v[1:])]
        out[k] = (float(np.std(v)), float(np.median(jumps)), float(np.percentile(jumps, 90)))
    out["f0_range"] = float(np.mean([p["f0_range"] for p in seq]))
    out["intra"] = float(np.mean([p["intra_sd"] for p in seq]))
    return out


def running(keys):
    chosen, hist = {}, {k: [] for k in KEYS}
    for i in usable:
        cs = cands(i)
        if not hist["active_db"]:
            pick = cs[0]
        else:
            med = {k: float(np.median(hist[k])) for k in KEYS}
            pick = min(cs, key=lambda s: sum(abs(feats[(i, s)][k] - med[k]) / scale[k] for k in keys))
        chosen[i] = pick
        for k in KEYS:
            hist[k].append(feats[(i, pick)][k])
    return chosen


def fmt(m):
    return " | ".join(f"{k} sd {m[k][0]:.2f} adj_med {m[k][1]:.2f} p90 {m[k][2]:.2f}" for k in KEYS) + f" | f0_range {m['f0_range']:.2f} intra {m['intra']:.2f}"


rng = np.random.default_rng(0)
draws = [metrics({i: int(rng.choice(cands(i))) for i in usable}) for _ in range(2000)]
print("first-pass      :", fmt(metrics({i: cands(i)[0] for i in usable})))
print("random pass     : mean over 2000 draws")
for k in KEYS:
    print(f"   {k}: sd {np.mean([d[k][0] for d in draws]):.2f} (p5-p95 {np.percentile([d[k][0] for d in draws], 5):.2f}-{np.percentile([d[k][0] for d in draws], 95):.2f}) adj_med {np.mean([d[k][1] for d in draws]):.2f} p90 {np.mean([d[k][2] for d in draws]):.2f}")
print(f"   f0_range {np.mean([d['f0_range'] for d in draws]):.2f} intra {np.mean([d['intra'] for d in draws]):.2f}")
for name, keys in (("running median (level+pitch+tilt)", KEYS), ("running median (level+tilt only)", ("active_db", "tilt")), ("running median (tilt only)", ("tilt",)), ("running median (level only)", ("active_db",))):
    c = running(keys)
    m = metrics(c)
    print(f"{name:34s}:", fmt(m))
    beat = [sum(d[k][0] > m[k][0] for d in draws) / len(draws) for k in KEYS]
    print("   share of random draws with larger sd (level, f0, tilt):", [round(x, 3) for x in beat])
