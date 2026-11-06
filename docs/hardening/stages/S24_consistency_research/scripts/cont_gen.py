import argparse
import json
import math
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/tmp/voice_measure")
ROOT = "/home/dbsdosdb/workspace/Lecture_Auto"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from bon_gen import REF, SEEDS, sentences  # noqa: E402

from lecture_auto.pipeline import raon_tts as R  # noqa: E402
from lecture_auto.pipeline.pronunciation import load_pronunciation_entries  # noqa: E402

GOLD_CLIP = f"{ROOT}/{REF}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("chain", "gold"), required=True)
    a = ap.parse_args()
    out = f"{ROOT}/data/audio_ref/comparison_s24/cont_{a.mode}"
    os.makedirs(out, exist_ok=True)
    texts = sentences(24)
    entries = load_pronunciation_entries(Path("config/pronunciation.yaml"))
    pipe = R.load_raon_pipeline(device="cuda:0")
    tuned = {k: pipe.task_params["tts"][k] for k in ("temperature", "ras_enabled", "ras_window_size", "ras_repetition_threshold")}
    pipe.task_params["tts_continuation"].update(tuned)
    print("continuation params", {k: pipe.task_params["tts_continuation"].get(k) for k in tuned}, flush=True)
    gold_text = pipe.stt(GOLD_CLIP) if a.mode == "gold" else None
    rows = []
    prev_path, prev_text = (GOLD_CLIP, gold_text) if a.mode == "gold" else (None, None)
    for i, text in enumerate(texts):
        expected = max(len(text) / R._CHARS_PER_SECOND, 3.0)
        cap = int(min(max(math.ceil(expected * R._CODEC_FRAME_RATE * R._TOKEN_CAP_RATIO) + 8, R._MIN_MAX_NEW_TOKENS), R._MAX_MAX_NEW_TOKENS))
        pipe.task_params["tts"]["max_new_tokens"] = cap
        pipe.task_params["tts_continuation"]["max_new_tokens"] = cap
        plan = [("cont", s) for s in SEEDS] if prev_path else []
        plan += [("plain", s) for s in SEEDS]
        accepted = None
        for mode, seed in plan:
            torch.manual_seed(seed)
            try:
                if mode == "cont":
                    wav, sr = pipe.tts_continuation(target_text=text, ref_audio=prev_path, ref_text=prev_text, speaker_audio=GOLD_CLIP)
                else:
                    wav, sr = pipe.tts(text, speaker_audio=GOLD_CLIP)
            except Exception as e:  # noqa: BLE001
                rows.append({"i": i, "mode": mode, "seed": seed, "error": repr(e)[:120]})
                print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
                continue
            trimmed = R._loudness_normalize(R._trim_lead_tail_silence(R._to_numpy(wav, sr), sr), sr)
            reasons = R._gate_reasons(trimmed, sr, expected)
            cer = status = None
            if not reasons:
                with tempfile.NamedTemporaryFile(suffix=".wav") as tmpf:
                    sf.write(tmpf.name, trimmed, sr)
                    check = R.evaluate_transcription(pipe, tmpf.name, text, entries)
                status, cer = check.status, check.cer
            ok = (not reasons) and status == "pass" and cer is not None and cer <= R._MAX_SEGMENT_CER
            rows.append({"i": i, "mode": mode, "seed": seed, "ok": bool(ok), "reasons": reasons, "cer": cer})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
            if ok:
                accepted = (mode, seed, trimmed, sr)
                break
        if accepted:
            mode, seed, trimmed, sr = accepted
            path = f"{out}/{i:02d}.wav"
            sf.write(path, trimmed, sr)
            if a.mode == "chain":
                prev_path, prev_text = path, text
            rows.append({"i": i, "accepted_mode": mode, "accepted_seed": seed})
        else:
            if a.mode == "chain":
                prev_path, prev_text = None, None
            rows.append({"i": i, "accepted_mode": None})
    json.dump({"texts": texts, "rows": rows}, open(f"{out}/rows.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
