import collections
import json
import os

import numpy as np
import soundfile as sf

src = open("/tmp/voice_measure/bon_analyze2.py").read().split("\nrng = np.random.default_rng(0)")[0]
ns = {}
exec(compile(src, "bon_analyze2", "exec"), ns)
feats, by, usable, SEEDS, KEYS = (ns[k] for k in ("feats", "by", "usable", "SEEDS", "KEYS"))
piece_stats, CMP = ns["ns"]["piece_stats"], ns["ns"]["CMP"]
metrics, fmt = ns["metrics"], ns["fmt"]


def first_pass_seq():
    return {i: next(s for s in SEEDS if s in by[i] and by[i][s]["ok"] and (i, s) in feats) for i in usable}


def load_mode(mode):
    d = f"{CMP}/cont_{mode}"
    rows = json.load(open(f"{d}/rows.json", encoding="utf-8"))["rows"]
    attempts = [r for r in rows if "mode" in r and "ok" in r]
    cont = [r for r in attempts if r["mode"] == "cont"]
    plain = [r for r in attempts if r["mode"] == "plain"]
    acc = {r["i"]: r["accepted_mode"] for r in rows if "accepted_mode" in r}
    f = {}
    for i in usable:
        p = f"{d}/{i:02d}.wav"
        if os.path.exists(p):
            w, sr = sf.read(p)
            w = (w if w.ndim == 1 else w[:, 0]).astype(np.float32)
            s = piece_stats(w, sr)
            if s:
                f[i] = s
    return rows, cont, plain, acc, f


def summarize(f):
    ids = sorted(f)
    seq = [f[i] for i in ids]
    out = {}
    for k in KEYS:
        v = [p[k] for p in seq]
        jumps = [abs(b - a) for a, b in zip(v, v[1:])]
        out[k] = (float(np.std(v)), float(np.median(jumps)), float(np.percentile(jumps, 90)))
    out["f0_range"] = float(np.mean([p["f0_range"] for p in seq]))
    out["intra"] = float(np.mean([p["intra_sd"] for p in seq]))
    return out, len(seq)


base_ids = first_pass_seq()
base = {i: feats[(i, base_ids[i])] for i in usable}
m, n = summarize(base)
print(f"baseline first-pass (plain, same sentences, n={n}):", fmt(m))
for mode in ("chain", "gold"):
    try:
        rows, cont, plain, acc, f = load_mode(mode)
    except FileNotFoundError:
        print(mode, "rows.json missing")
        continue
    ok_cont = sum(r["ok"] for r in cont)
    ok_plain = sum(r["ok"] for r in plain)
    print(f"\n[{mode}] continuation attempts {len(cont)} ok {ok_cont} ({100 * ok_cont / max(1, len(cont)):.0f}%); plain fallback attempts {len(plain)} ok {ok_plain}")
    print("   accepted mode counts:", dict(collections.Counter(acc.values())))
    m, n = summarize(f)
    print(f"   all accepted clips (n={n}):", fmt(m))
    only_cont = {i: f[i] for i in f if acc.get(i) == "cont"}
    if len(only_cont) >= 6:
        m2, n2 = summarize(only_cont)
        print(f"   only continuation-accepted clips (n={n2}):", fmt(m2))
