import numpy as np

src = open("/tmp/voice_measure/bon_analyze2.py").read().split("\nrng = np.random.default_rng(0)")[0]
ns = {}
exec(compile(src, "bon_analyze2", "exec"), ns)
feats, by, usable, SEEDS, KEYS, scale = (ns[k] for k in ("feats", "by", "usable", "SEEDS", "KEYS", "scale"))
metrics, fmt = ns["metrics"], ns["fmt"]


def cands_n(i, n):
    ok = [s for s in SEEDS if s in by[i] and by[i][s]["ok"] and (i, s) in feats]
    return ok[:n] if ok[:n] else ok[:1]


def running_n(keys, n):
    chosen, hist = {}, {k: [] for k in KEYS}
    for i in usable:
        cs = cands_n(i, n)
        if not hist["active_db"]:
            pick = cs[0]
        else:
            med = {k: float(np.median(hist[k])) for k in KEYS}
            pick = min(cs, key=lambda s: sum(abs(feats[(i, s)][k] - med[k]) / scale[k] for k in keys))
        chosen[i] = pick
        for k in KEYS:
            hist[k].append(feats[(i, pick)][k])
    return chosen


attempt_cost = {n: np.mean([min(n, len([s for s in SEEDS if s in by[i]])) for i in usable]) for n in (1, 2, 3, 4)}
print("candidates generated per sentence if N seeds are always drawn:", {n: round(float(v), 2) for n, v in attempt_cost.items()})
print("first-pass expected attempts per sentence (stop at first ok):", round(float(np.mean([1 + sum(1 for s in SEEDS[: SEEDS.index(cands_n(i, 1)[0])] if s in by[i]) for i in usable])), 2))
for n in (1, 2, 3, 4):
    for name, keys in (("level+pitch+tilt", KEYS), ("level only", ("active_db",)), ("level+tilt", ("active_db", "tilt"))):
        m = metrics(running_n(keys, n))
        print(f"N={n} {name:16s}:", fmt(m))
