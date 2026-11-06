"""Per-sentence timing and slide highlight boxes for a built lecture, for the student page.

Reads only what assembly left on disk (``<id>.timeline.json``, slide WAVs + QC sidecars,
scripts, the input PDF); never resynthesizes. ``scripts/annotate_lecture.py`` shares the
segment/cue helpers.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import soundfile as sf
from PIL import Image

from lecture_auto.pipeline.cache import qc_path_for, write_text_atomic
from lecture_auto.pipeline.highlight import load_blocks, map_segment
from lecture_auto.pipeline.pronunciation import apply_pronunciation
from lecture_auto.pipeline.subtitles import segment_spans, split_cue, written_segments
from lecture_auto.schemas.production import SlideQC, Timeline


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slide_segments(entry, audio_dir: Path, scripts_dir: Path, entries: list[dict]):
    """-> ((texts, spans, wav_seconds), info), or (None, info) when the slide must be skipped."""
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
    return (texts, spans, len(wav) / sr), info


def slide_cues(entry, audio_dir: Path, scripts_dir: Path, entries: list[dict]):
    """-> (cues, info), or (None, info) when the slide must be skipped."""
    seg, info = slide_segments(entry, audio_dir, scripts_dir, entries)
    if seg is None:
        return None, info
    texts, spans, _ = seg
    cues = [
        (entry.start_seconds + s, entry.start_seconds + e, t)
        for (s0, e0), txt in zip(spans, texts)
        for s, e, t in split_cue(txt, s0, e0)
    ]
    return cues, info



def load_timeline(lec_out: Path, lec_id: str) -> tuple[Timeline, str]:
    candidates = (lec_out / f"{lec_id}.timeline.json", lec_out / f"{lec_id}_DRAFT.timeline.json")
    tl_path = next((p for p in candidates if p.exists()), None)
    if tl_path is None:
        raise FileNotFoundError(f"no timeline.json under {lec_out}")
    return Timeline.model_validate_json(tl_path.read_text(encoding="utf-8")), tl_path.name[: -len(".timeline.json")]



def _titles_and_blocks(base: Path, png_width: int) -> tuple[dict, dict]:
    pdfs = sorted((base / "input").glob("*.pdf"))
    if not pdfs:
        return {}, {}
    blocks = load_blocks(pdfs[0], png_width)
    titles = {n: next((b.text for b in bs if not b.selectable and b.text.strip()), "") for n, bs in blocks.items()}
    return titles, blocks


def build_viewer(lec_id: str, work_dir: Path, output_dir: Path, entries: list[dict]) -> dict:
    """Everything the student page needs, with highlight boxes as fractions of the slide image."""
    timeline, _stem = load_timeline(output_dir / lec_id, lec_id)
    base = work_dir / lec_id
    first_png = base / "rendered" / f"slide_{timeline.entries[0].slide_number:03d}.png" if timeline.entries else None
    width, height = Image.open(first_png).size if first_png and first_png.exists() else (1, 1)
    titles, blocks = _titles_and_blocks(base, width)
    slides = []
    for entry in timeline.entries:
        n = entry.slide_number
        seg, _info = slide_segments(entry, base / "audio", base / "scripts", entries)
        sentences, cues = [], []
        if seg is not None:
            texts, spans, _ = seg
            by_id = {b.id: b for b in blocks.get(n, [])}
            prev = None
            for (s, e), text in zip(spans, texts):
                prev, _score = map_segment(text, blocks.get(n, []), prev)
                box = by_id[prev].bbox if prev is not None else None
                sentences.append({
                    "start": round(entry.start_seconds + s, 3), "end": round(entry.start_seconds + e, 3), "text": text,
                    "box": [round(box[0] / width, 4), round(box[1] / height, 4),
                            round(box[2] / width, 4), round(box[3] / height, 4)] if box else None,
                })
                cues += [{"start": round(entry.start_seconds + a, 3), "end": round(entry.start_seconds + b, 3), "text": t}
                         for a, b, t in split_cue(text, s, e)]
        slides.append({
            "number": n, "start": round(entry.start_seconds, 3), "duration": round(entry.duration_seconds, 3),
            "title": titles.get(n, ""), "sentences": sentences, "cues": cues,
        })
    return {
        "lecture_id": lec_id, "mp4": timeline.mp4, "draft": timeline.draft,
        "total_seconds": round(timeline.total_seconds, 3), "aspect": round(width / height, 4), "slides": slides,
    }


def viewer_path(output_dir: Path, lec_id: str) -> Path:
    return output_dir / lec_id / f"{lec_id}.viewer.json"


def write_viewer(lec_id: str, work_dir: Path, output_dir: Path, entries: list[dict]) -> Path:
    path = viewer_path(output_dir, lec_id)
    write_text_atomic(path, json.dumps(build_viewer(lec_id, work_dir, output_dir, entries), ensure_ascii=False))
    return path
