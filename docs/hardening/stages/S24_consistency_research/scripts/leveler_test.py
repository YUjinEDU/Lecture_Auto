import json
import sys

import numpy as np
import soundfile as sf

sys.argv = ["x", "/dev/null"]
ns = {}
exec(compile(open("/tmp/voice_measure/baseline3.py").read().split("\nreport = {}")[0], "b3", "exec"), ns)
pieces_of, summarize, production_like = ns["pieces_of"], ns["summarize"], ns["production_like"]
split_by_energy, block_db, read_mono = ns["split_by_energy"], ns["block_db"], ns["read_mono"]
CMP = ns["CMP"]


def active_level(x, sr):
    bd = block_db(x, sr)
    if bd is None:
        return None
    return float(np.median(bd[bd > bd.max() - 15]))


def level(wav, sr, alpha=1.0, clamp=4.0):
    spans = split_by_energy(wav, sr)
    levels = [active_level(wav[a:b], sr) for a, b in spans]
    keep = [(s, l) for s, l in zip(spans, levels) if l is not None]
    target = float(np.median([l for _, l in keep]))
    xs, ys = [0], [0.0]
    gains = []
    for (a, b), l in keep:
        g = float(np.clip(alpha * (target - l), -clamp, clamp))
        gains.append(g)
        xs += [a, b]
        ys += [g, g]
    xs.append(len(wav))
    ys.append(ys[-1])
    env = np.interp(np.arange(len(wav)), xs, ys)
    out = wav * (10 ** (env / 20)).astype(np.float32)
    peak = float(np.abs(out).max())
    if peak > 0.98:
        out = out * (0.98 / peak)
    return out.astype(np.float32), gains


report = {}
for ref in ("v2", "r216", "r390"):
    wav, sr = read_mono(f"{CMP}/listen_ok_{ref}.wav")
    base = production_like(wav, sr)
    report[f"{ref}:prod"] = summarize(pieces_of(base, sr, "f"))
    for alpha, clamp in ((1.0, 4.0), (0.6, 4.0)):
        lev, gains = level(base, sr, alpha=alpha, clamp=clamp)
        key = f"{ref}:prod+lev(a={alpha},c={clamp})"
        report[key] = summarize(pieces_of(lev, sr, "f"))
        report[key]["gain_db_abs_mean"] = round(float(np.mean(np.abs(gains))), 2)
        report[key]["gain_db_max_abs"] = round(float(np.max(np.abs(gains))), 2)
        sf.write(f"{CMP}/listen_lev{int(alpha * 10):02d}_{ref}.wav", lev, sr)
for k, v in report.items():
    print(k, json.dumps(v), flush=True)
json.dump(report, open(sys.argv[0] if False else "/tmp/voice_measure/leveler.json", "w"), indent=1)
