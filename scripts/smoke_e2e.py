#!/usr/bin/env python3
"""End-to-end smoke test for the unified pipeline (real models, real input).

Exercises exactly what the LLMClient / TTSEngine refactor changed, on a real
PDF, so you can confirm the integration actually works before deploying. Unit
tests mock every model — this does not.

Stages:
    parse  -> render(PNG) -> VLM(OpenAI) -> script(OpenAI) -> [TTS(local Qwen)]

Tiers (pick with --stage):
    --stage script  (DEFAULT)  parse+render+VLM+script. Needs OPENAI_API_KEY and
                               poppler (pdftoppm). NO GPU. Validates the ① change.
    --stage vlm                stop after VLM (cheapest OpenAI check).
    --stage render             parse+render only (no API, no GPU; checks poppler).
    --stage tts                full, incl. local Qwen3-TTS. Needs GPU + qwen-tts
                               installed and the driver mismatch fixed (② change).

Usage:
    export OPENAI_API_KEY=sk-...
    uv run python scripts/smoke_e2e.py "PPTX/04-SQL 1.pdf" --max-slides 2
    uv run python scripts/smoke_e2e.py path/to.pdf --stage tts --voice voice.wav

Outputs land under data/smoke/<pdf-stem>/{rendered,vlm,scripts,audio}/.
Cost note: each slide = 1 OpenAI vision call + 1 text call. Keep --max-slides small.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# Make the package importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STAGES = ["render", "vlm", "script", "tts"]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _hr(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf", type=Path, help="Input PDF (or PPTX) to run through the pipeline")
    ap.add_argument("--stage", choices=STAGES, default="script", help="How far to run (default: script)")
    ap.add_argument("--max-slides", type=int, default=2, help="Cap slides to limit cost/time (default: 2)")
    ap.add_argument("--minutes", type=int, default=10, help="Target lecture minutes (drives sec/slide)")
    ap.add_argument("--voice", type=Path, default=None, help="Optional voice reference WAV for TTS cloning")
    ap.add_argument("--out", type=Path, default=None, help="Output root (default: data/smoke/<stem>)")
    args = ap.parse_args()

    src: Path = args.pdf.resolve()
    if not src.exists():
        print(f"ERROR: input not found: {src}", file=sys.stderr)
        return 1

    target_stage = STAGES.index(args.stage)
    out_root = (args.out or Path("data/smoke") / src.stem).resolve()
    rendered_dir = out_root / "rendered"
    vlm_dir = out_root / "vlm"
    scripts_dir = out_root / "scripts"
    audio_dir = out_root / "audio"
    for d in (rendered_dir, vlm_dir, scripts_dir, audio_dir):
        d.mkdir(parents=True, exist_ok=True)

    print(f"Input : {src}")
    print(f"Out   : {out_root}")
    print(f"Stage : {args.stage}  | max-slides: {args.max_slides}")

    # ---- Stage 0: parse -------------------------------------------------
    _hr("PARSE")
    from lecture_auto.pipeline.parser_pdf import parse_input
    from lecture_auto.schemas.manifest import LectureStyle, SlideManifest

    slides = parse_input(src)
    if args.max_slides > 0:
        slides = slides[: args.max_slides]
    # Normalize index/number/png_path so VLM and TTS find the rendered files.
    slides = [
        s.model_copy(update={
            "slide_index": i,
            "slide_number": i + 1,
            "png_path": f"slide_{i + 1:03d}.png",
        })
        for i, s in enumerate(slides)
    ]
    print(f"  parsed slides: {len(slides)}")

    manifest = SlideManifest(
        job_id="smoke",
        file_sha256=_sha256(src),
        lecture_name=src.stem,
        subject_name="Smoke Test",
        target_audience="undergraduate",
        target_minutes=args.minutes,
        style=LectureStyle(density="detailed", tone="formal", approach="explanatory"),
        slide_count=len(slides),
        slides=slides,
    )

    # ---- Stage 1: render (PDF -> PNG) -----------------------------------
    _hr("RENDER")
    from lecture_auto.pipeline.renderer import pdf_to_pngs, render_slides

    if src.suffix.lower() == ".pdf":
        png_paths = pdf_to_pngs(src, rendered_dir)
    else:  # .pptx -> PDF -> PNG (needs soffice)
        png_paths, _ = render_slides(src, rendered_dir, "smoke")
    png_paths = png_paths[: len(slides)]
    print(f"  rendered PNGs: {len(png_paths)} -> {rendered_dir}")
    if target_stage == STAGES.index("render"):
        print("\nrender OK ✅ (stopped at --stage render)")
        return 0

    # ---- Stage 2: VLM (OpenAI vision) -----------------------------------
    _hr("VLM (OpenAI)")
    from lecture_auto.llm import get_llm_client
    from lecture_auto.pipeline.vlm import generate_visual_notes

    client = get_llm_client()
    notes = generate_visual_notes(client, slides, rendered_dir, vlm_dir)
    print(f"  VLM notes: {len(notes)} -> {vlm_dir}")
    print(f"  sample summary: {notes[0].visual_summary[:120]!r}")
    print(f"  needs_review flags: {[n.needs_review for n in notes]}")
    if target_stage == STAGES.index("vlm"):
        print("\nVLM OK ✅ (stopped at --stage vlm)")
        return 0

    # ---- Stage 3: script (OpenAI text) ----------------------------------
    _hr("SCRIPT (OpenAI)")
    from lecture_auto.pipeline.script_gen import generate_scripts

    scripts = generate_scripts(
        slides, [n.model_dump() for n in notes], manifest, scripts_dir, client=client
    )
    print(f"  scripts: {len(scripts)} -> {scripts_dir}")
    print(f"  sample script: {scripts[0].script[:160]!r}")
    if target_stage == STAGES.index("script"):
        print("\nVLM + SCRIPT OK ✅ (① OpenAI path verified; stopped before TTS)")
        return 0

    # ---- Stage 4: TTS (local Qwen3-TTS) ---------------------------------
    _hr("TTS (local Qwen3-TTS)")
    from lecture_auto.tts import get_tts_engine

    engine = get_tts_engine()
    voice = args.voice.resolve() if args.voice else None
    for sc in scripts:
        out = audio_dir / f"audio_{sc.slide_number:03d}.wav"
        engine.synthesize_slide(sc.script, out, voice_ref_path=voice)
        print(f"  wrote {out}")
    print("\nFULL E2E OK ✅ (① OpenAI + ② local TTS verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
