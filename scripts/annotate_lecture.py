"""S14 CLI: sentence-level subtitles (SRT/VTT/JSON) for an already-built lecture.

    python scripts/annotate_lecture.py --only 08_ [--burn] [--font NanumSquareRound]
        [--work-dir data/work_batch] [--output-dir output] [--out-dir DIR]

Reads ``<output-dir>/<id>/<stem>.timeline.json`` + ``<work-dir>/<id>/{audio,scripts}``;
never resynthesizes. Writes ``<stem>.srt/.vtt/.subtitles.json`` (and with ``--burn``
``<stem>_subtitled.mp4``, original mp4 untouched) into ``--out-dir`` (default: the
lecture's output folder).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import soundfile as sf

# Make this checkout's lecture_auto win over any other editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lecture_auto.pipeline.cache import qc_path_for, write_text_atomic
from lecture_auto.pipeline.pronunciation import apply_pronunciation, load_pronunciation_entries
from lecture_auto.pipeline.subtitles import segment_spans, split_cue, to_srt, to_vtt, written_segments
from lecture_auto.schemas.production import SlideQC, Timeline

try:
    from scripts.batch_generate_lectures import LECTURES
except ImportError:  # run as ``python scripts/annotate_lecture.py``
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from batch_generate_lectures import LECTURES

REPO = Path(__file__).resolve().parent.parent


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slide_cues(entry, audio_dir: Path, scripts_dir: Path, entries: list[dict]):
    """-> (cues, info), or (None, info) when the slide must be skipped."""
    n = entry.slide_number
    info: dict = {"slide": n}
    wav_path = audio_dir / entry.wav
    if not wav_path.exists() or _sha(wav_path) != entry.wav_sha256:
        info["skipped"] = "wav sha256 differs from timeline (or wav missing)"
        return None, info
    script = json.loads((scripts_dir / f"script_{n:03d}.json").read_text(encoding="utf-8"))["script"]
    wav, sr = sf.read(str(wav_path), dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    qc_file = qc_path_for(wav_path)
    qc = SlideQC.model_validate_json(qc_file.read_text(encoding="utf-8")) if qc_file.exists() else None
    if qc is None or not qc.segments:
        texts, spans, method, source = [script], [(0.0, len(wav) / sr)], "proportional", "written"
    else:
        spoken = [s.text for s in qc.segments]
        spans, method = segment_spans(wav, sr, len(spoken), [len(t) for t in spoken])
        spoken_full = apply_pronunciation(script, entries)
        hash_ok = qc.spoken_text_sha256 in {
            hashlib.sha256(t.encode("utf-8")).hexdigest() for t in (spoken_full, spoken_full.strip())
        }
        written = written_segments(script, spoken, entries) if hash_ok else None
        texts, source = (written, "written") if written else (spoken, "spoken")
        if not hash_ok:
            info["spoken_hash_mismatch"] = True
    info.update(method=method, source=source)
    cues = [
        (entry.start_seconds + s, entry.start_seconds + e, t)
        for (s0, e0), txt in zip(spans, texts)
        for s, e, t in split_cue(txt, s0, e0)
    ]
    return cues, info


def _esc(p: str) -> str:
    return p.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace(",", "\\,")


def burn(mp4: Path, srt: Path, out: Path, font: str) -> None:
    """Re-encode video only (``-c:a copy``); the subtitle is addressed relative to cwd to dodge path escaping."""
    style = f"FontName={font},FontSize=22,Outline=2"
    vf = f"subtitles='{_esc(srt.name)}':force_style='{style}'"
    cmd = ["ffmpeg", "-y", "-i", str(mp4), "-vf", vf, "-c:v", "libx264", "-c:a", "copy", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=srt.parent)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {res.returncode}):\n{res.stderr[-2000:]}")


def run(lec_id: str, work_dir: Path, output_dir: Path, out_dir: Path | None, entries: list[dict],
        do_burn: bool = False, font: str = "NanumSquareRound") -> dict:
    lec_out = output_dir / lec_id
    candidates = (lec_out / f"{lec_id}.timeline.json", lec_out / f"{lec_id}_DRAFT.timeline.json")
    tl_path = next((p for p in candidates if p.exists()), None)
    if tl_path is None:
        raise FileNotFoundError(f"no timeline.json under {lec_out}")
    timeline = Timeline.model_validate_json(tl_path.read_text(encoding="utf-8"))
    stem = tl_path.name[: -len(".timeline.json")]
    out_dir = out_dir or lec_out
    out_dir.mkdir(parents=True, exist_ok=True)
    cues, slides = [], []
    for entry in timeline.entries:
        c, info = _slide_cues(entry, work_dir / lec_id / "audio", work_dir / lec_id / "scripts", entries)
        slides.append(info)
        cues += c or []
    cues.sort(key=lambda x: x[0])
    write_text_atomic(out_dir / f"{stem}.srt", to_srt(cues))
    write_text_atomic(out_dir / f"{stem}.vtt", to_vtt(cues))

    def count(k, v):
        return sum(1 for s in slides if s.get(k) == v)

    summary = {
        "slides": len(slides), "pause": count("method", "pause"), "proportional": count("method", "proportional"),
        "written": count("source", "written"), "spoken": count("source", "spoken"),
        "skipped": [s["slide"] for s in slides if "skipped" in s], "cues": len(cues),
        "spoken_hash_mismatch": [s["slide"] for s in slides if s.get("spoken_hash_mismatch")],
    }
    write_text_atomic(
        out_dir / f"{stem}.subtitles.json",
        json.dumps({"summary": summary, "slides": slides,
                    "cues": [{"start": s, "end": e, "text": t} for s, e, t in cues]},
                   ensure_ascii=False, indent=2),
    )
    if do_burn:
        burn(lec_out / timeline.mp4, out_dir / f"{stem}.srt", out_dir / f"{stem}_subtitled.mp4", font)
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", required=True, help="substring of the lecture id")
    ap.add_argument("--burn", action="store_true")
    ap.add_argument("--font", default="NanumSquareRound")
    ap.add_argument("--work-dir", type=Path, default=Path("data/work_batch"))
    ap.add_argument("--output-dir", type=Path, default=Path("output"))
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--pronunciation", type=Path, default=REPO / "config" / "pronunciation.yaml")
    args = ap.parse_args(argv)
    matched = [lec["id"] for lec in LECTURES if args.only in lec["id"]]
    if len(matched) != 1:
        ap.error(f"--only {args.only!r} matched {len(matched)} lectures: {matched}")
    entries = load_pronunciation_entries(args.pronunciation)
    s = run(matched[0], args.work_dir, args.output_dir, args.out_dir, entries, args.burn, args.font)
    print(f"slides={s['slides']} pause={s['pause']} proportional={s['proportional']} "
          f"written={s['written']} spoken={s['spoken']} cues={s['cues']} skipped={s['skipped']} "
          f"spoken_hash_mismatch={s['spoken_hash_mismatch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
