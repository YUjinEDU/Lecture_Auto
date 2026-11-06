import glob
import subprocess
import sys

import numpy as np
import soundfile as sf

sys.argv = ["x", "/dev/null"]
ns = {}
exec(compile(open("/tmp/voice_measure/baseline3.py").read().split("\nreport = {}")[0], "b3", "exec"), ns)
pieces_of, summarize = ns["pieces_of"], ns["summarize"]
ROOT = "/home/dbsdosdb/workspace/Lecture_Auto"
LEC = f"{ROOT}/data/work_batch/10_종합설계_07_시스템구조_자유분량"
MP4 = glob.glob(f"{ROOT}/output/10_종합설계_07_시스템구조_자유분량/10_*_18분.mp4")[0]
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", MP4, "-t", "420", "-ac", "1", "-ar", "24000", "/tmp/voice_measure/enc10.wav"], check=True)
dec, sr = sf.read("/tmp/voice_measure/enc10.wav")
dec = dec.astype(np.float32)
info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,channels,sample_rate,bit_rate", "-of", "compact=p=0", MP4], capture_output=True, text=True).stdout
print(info.strip().replace("\n", " | "))
parts, total = [], 0
for f in sorted(glob.glob(f"{LEC}/audio/slide_*.wav")):
    if f.endswith((".cand.wav", ".prev.wav")):
        continue
    w, wsr = sf.read(f)
    w = (w if w.ndim == 1 else w[:, 0]).astype(np.float32)
    parts.append(w)
    total += len(w) / wsr
    if total >= 420:
        break
src = np.concatenate(parts)[: len(dec)]
for name, wav in (("source slide wavs (first 7 min)", src), ("decoded final mp4 (first 7 min)", dec[: len(src)])):
    print(name, summarize(pieces_of(wav, sr, "x"))["active_db"], "peak", round(float(np.abs(wav).max()), 3))
