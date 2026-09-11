<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# tests/demo — demo-layer tests

## Purpose
Tests for the demo orchestration surface (`lecture_auto/demo/` + `api/routes/demo.py`),
focused on slide TTS status transitions and the approve flow.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Test package marker. |
| `test_approve_endpoint.py` | Slide TTS status defaults to `pending`; `upsert_slide` preserves existing fields; approve returns OK and flips slide status to `queued`; job dict includes `tts_done_slides`. |

## For AI Agents

### Working In This Directory
- Keep these aligned with `lecture_auto/demo/state.py` (the `DemoJob`/slide model) and the
  demo route handlers.
- Assert state transitions, not implementation details — `pending → queued → done`.

### Testing Requirements
- `pytest tests/demo`. No GPU/Redis; demo state is in-memory.

## Dependencies

### Internal
- `lecture_auto/demo/`, `lecture_auto/api/routes/demo.py`.

### External
- `pytest`.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
