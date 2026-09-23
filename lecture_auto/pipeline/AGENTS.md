<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# pipeline — the shared stage core

## Purpose
Pure, driver-agnostic stage modules that implement the lecture pipeline. Each stage takes
typed inputs and writes typed artifacts; none of them know about Celery, FastAPI, or the
demo. The canonical order:

```
parse (pptx/pdf) → render (PNG) → VLM (visual notes) → script (Claude) → TTS (audio) → video (mp4)
```

Stages are designed so the **atomic unit is one slide**, which is what makes the async and
demo layers resumable.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Re-exports every stage symbol for easy top-level import. |
| `parser_pptx.py` | PPTX → `list[SlideRecord]` via python-pptx; extracts font info, classifies shapes (title/body/image/other). |
| `parser_pdf.py` | PDF → `SlideRecord` via PyMuPDF; title detection, pt→EMU bbox, pdfplumber table fallback. Exposes `parse_input()` dispatcher: `.pdf` → direct, `.pptx` → LibreOffice → PDF → parse. |
| `renderer.py` | `render_slides()`: PPTX → PDF (LibreOffice headless) → numbered PNGs (pdf2image), plus font-issue detection. |
| `tofu_detector.py` | Korean font-substitution / "tofu" (□□□) detection from `soffice` stderr + near-white pixel heuristic. |
| `vlm.py` | Qwen3-VL via vLLM offline inference. Builds **text-grounded** multimodal prompts, generates per-slide `VlmNote`, computes token overlap. |
| `script_gen.py` | Lecture-script generation by calling `claude -p` as an asyncio subprocess; builds style/context prompts, parses JSON. |
| `tts.py` | Qwen3-TTS voice-clone synthesis: per-slide WAV + silence handling. `merge_audio()` takes a directory (glob, legacy callers) **or an explicit ordered WAV list** (no glob). |
| `raon_tts.py` | Raon-Speech-9B synthesis used by the production batch: segment splitting, seed retries, continuation, energy/silence quality gate, loudness normalization. `evaluate_transcription()` → `TranscriptionCheck` (`pass`/`fail`/`unavailable` + CER, recorded only — no CER threshold); `check_transcription_fidelity()` is its legacy `reasons` wrapper. |
| `cache.py` | Content-hash sidecar cache (`content_hash`, `is_cache_valid`, `write_cache_hash`, `write_text_atomic`). |
| `video.py` | `assemble_video()`: single ffmpeg pass (concat demuxer of slide PNGs + merged audio of exactly the resolved slide WAVs). `strict=True` raises on a missing WAV instead of skipping. |

## For AI Agents

### Working In This Directory
- **Keep these pure.** No progress publishing, no DB, no queue logic — that lives in the
  drivers (`tasks/`, `demo/`, `run.py`). Adding a Redis import here is a smell.
- Output is the contract: write artifacts as `*_NNN.json` / `slide_NNN.png` /
  `audio_NNN.wav` with **3-digit zero-padded slide numbers**, and write JSON atomically.
- Subprocess stages (`soffice`, `claude`, `ffmpeg`) must `check=True`, `capture_output`,
  and raise a clear error on non-zero exit. Use a **per-job `soffice` UserInstallation**
  temp dir to avoid LibreOffice lock-file races under concurrency.

### Testing Requirements
- Mirror tests in `tests/test_<module>.py`; all externals are mocked. Don't call real
  vLLM/TTS/ffmpeg/soffice in tests.

### Common Patterns & domain rules
- **Hallucination guard (VLM-02):** parsed slide text is injected into the VLM prompt.
  After generation, `compute_token_overlap()` flags `needs_review=True` when the slide has
  >10 parsed tokens and overlap `< 0.30`.
- **VLM retry:** first pass `temperature=0.3`; on JSON-parse failure retry once at `0.1`.
- **Reproducibility:** deterministic file naming + low temperatures keep reruns stable.

## Dependencies

### Internal
- `lecture_auto/schemas/manifest.py` (`SlideRecord`, `ShapeRecord`, `LectureStyle`).

### External
- vLLM + qwen-vl-utils, qwen-tts, PyMuPDF, pdfplumber, python-pptx, pdf2image/poppler,
  Pillow, soundfile, LibreOffice, ffmpeg, Claude CLI.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
