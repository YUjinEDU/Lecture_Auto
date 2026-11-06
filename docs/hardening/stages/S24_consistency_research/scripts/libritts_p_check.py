import csv
import math
import statistics as st
import sys
from collections import defaultdict

path, excl = sys.argv[1], sys.argv[2]
excluded = {l.strip() for l in open(excl, encoding="utf-8") if l.strip()}
rows = list(csv.DictReader(open(path, encoding="utf-8")))
print("rows", len(rows), "columns", list(rows[0])[:14])
groups = defaultdict(list)
dropped_invalid = 0
for r in rows:
    if str(r.get("invalid", "0")) not in ("0", "0.0", ""):
        dropped_invalid += 1
        continue
    spk = str(r["spk_id"])
    if spk in excluded:
        continue
    chapter = str(r["item_name"]).split("_")[1]
    try:
        lufs = float(r["raw_loudness_lufs"])
        f0 = float(r["raw_f0_mean"])
    except (ValueError, KeyError):
        continue
    if not math.isfinite(lufs) or f0 <= 0:
        continue
    groups[(spk, chapter)].append((lufs, 12 * math.log2(f0)))
print("invalid dropped", dropped_invalid, "excluded speakers", len(excluded))
sd_l, sd_f, rng_l, rng_f, n_utt = [], [], [], [], 0
for g in groups.values():
    if len(g) < 20:
        continue
    l = [x[0] for x in g]
    f = [x[1] for x in g]
    sd_l.append(st.stdev(l))
    sd_f.append(st.stdev(f))
    q = lambda v, p: sorted(v)[int(p * (len(v) - 1))]
    rng_l.append(q(l, 0.95) - q(l, 0.05))
    rng_f.append(q(f, 0.95) - q(f, 0.05))
    n_utt += len(g)
print(f"groups {len(sd_l)} utterances {n_utt}")
print(f"loudness sd median {st.median(sd_l):.3f} LU  p10-p90 {sorted(sd_l)[int(.1 * len(sd_l))]:.3f}-{sorted(sd_l)[int(.9 * len(sd_l))]:.3f}; P95-P05 median {st.median(rng_l):.3f}")
print(f"F0(mean per utt, semitones) sd median {st.median(sd_f):.3f}  p10-p90 {sorted(sd_f)[int(.1 * len(sd_f))]:.3f}-{sorted(sd_f)[int(.9 * len(sd_f))]:.3f}; P95-P05 median {st.median(rng_f):.3f}")
