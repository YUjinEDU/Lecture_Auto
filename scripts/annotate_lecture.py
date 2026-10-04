"""S14 CLI: sentence-level subtitles (SRT/VTT/JSON) for an already-built lecture.

    python scripts/annotate_lecture.py --only 08_ [--burn] [--font NanumSquareRound]
        [--work-dir data/work_batch] [--output-dir output] [--out-dir DIR]
    python scripts/annotate_lecture.py --only 08_ --highlight [--slides 3-5] [--burn] --out-dir DIR

``--highlight`` (S15) writes ``<stem>_annotated.mp4`` (+ ``<stem>.highlight.json``): the slide
text block each sentence is about gets a marker + underline. Video only is re-encoded; audio is
the existing WAVs. ``--slides`` limits it to a short preview. Frames go to a temp dir under
``--out-dir`` that is removed afterwards.

Reads ``<output-dir>/<id>/<stem>.timeline.json`` + ``<work-dir>/<id>/{audio,scripts}``;
never resynthesizes. Writes ``<stem>.srt/.vtt/.subtitles.json`` (and with ``--burn``
``<stem>_subtitled.mp4``, original mp4 untouched) into ``--out-dir`` (default: the
lecture's output folder).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import soundfile as sf
from PIL import Image

# Make this checkout's lecture_auto win over any other editable install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lecture_auto.pipeline.cache import qc_path_for, write_text_atomic
from lecture_auto.pipeline.highlight import concat_manifest, draw_highlight, load_blocks, map_segment, slide_pieces
from lecture_auto.pipeline.tts import merge_audio
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


def _slide_segments(entry, audio_dir: Path, scripts_dir: Path, entries: list[dict]):
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


def _slide_cues(entry, audio_dir: Path, scripts_dir: Path, entries: list[dict]):
    """-> (cues, info), or (None, info) when the slide must be skipped."""
    seg, info = _slide_segments(entry, audio_dir, scripts_dir, entries)
    if seg is None:
        return None, info
    texts, spans, _ = seg
    cues = [
        (entry.start_seconds + s, entry.start_seconds + e, t)
        for (s0, e0), txt in zip(spans, texts)
        for s, e, t in split_cue(txt, s0, e0)
    ]
    return cues, info


def _esc(p: str) -> str:
    return p.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:").replace(",", "\\,")


def burn(mp4: Path, srt: Path, out: Path, font: str) -> None:
    """Re-encode video only (``-c:a copy``) with a caption band below the slide; the subtitle
    is addressed relative to cwd to dodge path escaping."""
    # Slides fill the frame edge to edge, so overlaid captions cover content. Add an
    # 18% black band under the slide and set the captions inside it instead.
    style = f"FontName={font},FontSize=14,Outline=0,MarginV=6"
    vf = f"pad=iw:trunc(ih*1.18/2)*2:0:0:color=black,subtitles='{_esc(srt.name)}':force_style='{style}'"
    # cwd is srt.parent (see docstring), so every other path must be absolute.
    cmd = ["ffmpeg", "-y", "-i", str(mp4.resolve()), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
           "-c:a", "copy", str(out.resolve())]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=srt.parent)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {res.returncode}):\n{res.stderr[-2000:]}")


def _load_timeline(lec_out: Path, lec_id: str) -> tuple[Timeline, str]:
    candidates = (lec_out / f"{lec_id}.timeline.json", lec_out / f"{lec_id}_DRAFT.timeline.json")
    tl_path = next((p for p in candidates if p.exists()), None)
    if tl_path is None:
        raise FileNotFoundError(f"no timeline.json under {lec_out}")
    return Timeline.model_validate_json(tl_path.read_text(encoding="utf-8")), tl_path.name[: -len(".timeline.json")]


def parse_slides(spec: str) -> set[int]:
    """"3-5" / "3,5,7" / "2-4,9" -> {slide numbers}."""
    out: set[int] = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def _encode(manifest: Path, audio: Path, total: float, out: Path) -> None:
    """Same encoding options as ``video.assemble_video`` (all paths absolute)."""
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(manifest.resolve()), "-i", str(audio.resolve()),
           "-t", f"{total:.6f}", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30", "-c:v", "libx264",
           "-preset", "veryfast", "-c:a", "aac", "-b:a", "192k", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-shortest", str(out.resolve())]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {res.returncode}):\n{res.stderr[-2000:]}")


def run_highlight(lec_id: str, work_dir: Path, output_dir: Path, out_dir: Path | None, entries: list[dict],
                  slides: set[int] | None = None, do_burn: bool = False, font: str = "NanumSquareRound") -> dict:
    lec_out = output_dir / lec_id
    timeline, stem = _load_timeline(lec_out, lec_id)
    out_dir = out_dir or lec_out
    out_dir.mkdir(parents=True, exist_ok=True)
    base = work_dir / lec_id
    pdfs = sorted((base / "input").glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"no PDF under {base / 'input'}")
    png = lambda n: base / "rendered" / f"slide_{n:03d}.png"  # noqa: E731
    sel = [e for e in timeline.entries if slides is None or e.slide_number in slides]
    if not sel:
        raise ValueError(f"no timeline entries match --slides {sorted(slides or [])}")
    blocks = load_blocks(pdfs[0], Image.open(png(sel[0].slide_number)).width)
    tmp = out_dir / f"{stem}.annotate_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        items, wavs, cues, slide_info, cum = [], [], [], [], 0.0
        for entry in sel:
            seg, info = _slide_segments(entry, base / "audio", base / "scripts", entries)
            if seg is None:
                slide_info.append(info)
                continue
            texts, spans, dur = seg
            n = entry.slide_number
            sblocks = blocks.get(n, [])
            ids, scores, prev = [], [], None
            for t in texts:
                prev, sc = map_segment(t, sblocks, prev)
                ids.append(prev)
                scores.append(round(sc, 3))
            by_id = {b.id: b for b in sblocks}
            frame: dict[int | None, Path] = {None: png(n)}
            for bid in {i for i in ids if i is not None}:
                dest = tmp / f"slide_{n:03d}_b{bid}.png"
                draw_highlight(png(n), by_id[bid].bbox).save(dest)
                frame[bid] = dest
            pieces = slide_pieces(spans, ids, dur)
            items += [(frame[b], d) for b, d in pieces]
            wavs.append(base / "audio" / entry.wav)
            # keep the timeline's own clock for full runs; previews re-base to 0
            shifted = entry.model_copy(update={"start_seconds": entry.start_seconds if slides is None else cum})
            cum += dur
            c, _ = _slide_cues(shifted, base / "audio", base / "scripts", entries)
            cues += c or []
            info.update(
                segments=[{"start": round(a, 3), "end": round(b, 3), "block": i, "score": s, "text": t}
                          for (a, b), i, s, t in zip(spans, ids, scores, texts)],
                pieces=[{"block": b, "seconds": round(d, 6)} for b, d in pieces],
                highlighted=sum(i is not None for i in ids), n_segments=len(ids),
            )
            slide_info.append(info)
        if not items:
            raise RuntimeError("no slide could be assembled (all skipped)")
        merged = merge_audio(wavs, tmp / "merged.wav")
        total = sum(d for _, d in items)
        man = tmp / "frames.txt"
        man.write_text(concat_manifest(items), encoding="utf-8")
        final = out_dir / f"{stem}_annotated.mp4"
        if do_burn:
            cues.sort(key=lambda x: x[0])
            (tmp / "cues.srt").write_text(to_srt(cues), encoding="utf-8")
            _encode(man, merged, total, tmp / "plain.mp4")
            burn(tmp / "plain.mp4", tmp / "cues.srt", final, font)
        else:
            _encode(man, merged, total, final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    done = [s for s in slide_info if "segments" in s]
    n_seg = sum(s["n_segments"] for s in done)
    n_hl = sum(s["highlighted"] for s in done)
    summary = {"slides": len(done), "segments": n_seg, "highlighted": n_hl,
               "coverage": round(n_hl / n_seg, 3) if n_seg else 0.0,
               "skipped": [s["slide"] for s in slide_info if "skipped" in s], "seconds": round(total, 3)}
    write_text_atomic(out_dir / f"{stem}.highlight.json",
                      json.dumps({"summary": summary, "slides": slide_info}, ensure_ascii=False, indent=2))
    return summary


def run(lec_id: str, work_dir: Path, output_dir: Path, out_dir: Path | None, entries: list[dict],
        do_burn: bool = False, font: str = "NanumSquareRound") -> dict:
    lec_out = output_dir / lec_id
    timeline, stem = _load_timeline(lec_out, lec_id)
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
    ap.add_argument("--highlight", action="store_true", help="S15: write <stem>_annotated.mp4 with block highlights")
    ap.add_argument("--slides", default=None, help="with --highlight: only these slides, e.g. 3-5 (preview)")
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
    if args.highlight:
        h = run_highlight(matched[0], args.work_dir, args.output_dir, args.out_dir, entries,
                          parse_slides(args.slides) if args.slides else None, args.burn, args.font)
        print(f"slides={h['slides']} segments={h['segments']} highlighted={h['highlighted']} "
              f"coverage={h['coverage']:.0%} skipped={h['skipped']} seconds={h['seconds']}")
        return 0
    s = run(matched[0], args.work_dir, args.output_dir, args.out_dir, entries, args.burn, args.font)
    print(f"slides={s['slides']} pause={s['pause']} proportional={s['proportional']} "
          f"written={s['written']} spoken={s['spoken']} cues={s['cues']} skipped={s['skipped']} "
          f"spoken_hash_mismatch={s['spoken_hash_mismatch']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
