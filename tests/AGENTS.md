<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# tests — pytest suite

## Purpose
Unit + integration tests mirroring the backend modules. The suite runs **without GPU or
network**: vLLM, Qwen-TTS, `claude -p`, `soffice`, `ffmpeg`, and Redis are all mocked or
faked. Tests double as executable specs for the pipeline's contracts (title-detection
rules, EMU conversion, token-overlap thresholds, ffmpeg flags, SSE behavior).

## Key Files
| File | Description |
|------|-------------|
| `test_parser.py` | PPTX parsing: slide indexing, shape classification, title/body roles, SmartArt/chart/OLE handling. |
| `test_parser_pdf.py` | PDF parsing: title detection (`y<0.25H AND (font≥18 OR bold)`), pt→EMU (`×12700`), image blocks, table fallback, PPTX→PDF dispatch. |
| `test_renderer.py` | LibreOffice + pdf2image: `soffice` arg correctness, temp-dir cleanup, `slide_NNN.png` naming, DPI. |
| `test_tofu_detector.py` | Korean font-issue detection from `soffice` stderr + pixel analysis. |
| `test_vlm.py` | VLM note generation, schema validation, malformed-JSON retry. |
| `test_token_overlap.py` | Token-overlap ratio + `needs_review` heuristic, extended `VlmNote`. |
| `test_script_gen.py` | Claude script prompts (context window, style params, target seconds) + JSON parsing. |
| `test_tts.py` | TTS file naming, voice-ref forwarding, empty/whitespace → silence. |
| `test_video.py` | ffmpeg clip/concat command shape, cleanup, assemble flow. |
| `test_progress.py` | Redis pub/sub progress publisher persistence. |
| `test_jobs_api.py` | Job submit/status/SSE integration via FastAPI `TestClient`. |
| `test_scripts_api.py` | Script CRUD/regenerate/approve/progress/PNG endpoints. |
| `test_script_tasks.py` | Resumable script Celery task + checkpointing. |
| `test_vlm_tasks.py` | Resumable VLM Celery task. |
| `test_run.py` | CLI helpers (`confirm_step`, arg parser, `write_summary`, `sha256_file`). |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `demo/` | Tests for the demo orchestration layer (see `demo/AGENTS.md`). |

## For AI Agents

### Working In This Directory
- Mirror the source: a change in `lecture_auto/pipeline/X.py` belongs in `tests/test_X.py`.
- **Mock the externals, never call them.** Use `unittest.mock` for vLLM/TTS/subprocess;
  build tiny real PDFs/PPTX/WAVs in-memory when a fixture needs real bytes.
- Discovery is `Test*` classes / `test_*` functions (see `pyproject.toml`).

### Testing Requirements
- `pytest` from repo root. `pytest-asyncio` is available for async subprocess tests.

### Common Patterns
- Fixtures fabricate minimal artifacts (`_create_simple_pdf`, `make_test_pptx`,
  `_make_silence_wav`) rather than committing binaries.
- API tests inject a mock `JobPaths` pointing at `tmp_path`.

## Dependencies

### Internal
- Imports the modules under `lecture_auto/`.

### External
- `pytest`, `pytest-asyncio` (dev extras in `pyproject.toml`).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
