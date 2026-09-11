<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# schemas — Pydantic v2 contracts

## Purpose
The typed boundary between every layer. The pipeline produces these models, the tasks
checkpoint them as JSON, the API serializes them, and the portal's TypeScript types mirror
them. Change a model here and you change the contract for all four.

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Re-export marker for the schema package. |
| `manifest.py` | The parse-stage data model: `FontInfo`, `TextRun`, `TextParagraph`, `ShapeRecord`, `SlideRecord`, `LectureStyle`, and the top-level `SlideManifest`. |
| `job_status.py` | `JobStatus` enum + `ProgressEvent` (job_id, stage, current/total, percent, status) — the SSE/progress contract. |
| `script.py` | `ScriptUpdateRequest`, `ScriptResponse`, `ScriptApproveResponse` for the script CRUD endpoints. |
| `tts.py` | `VoiceRegisterResponse`, `TTSStatusResponse`, `TTSRegenerateResponse`, `PackageResponse`. |
| `request.py` | `UploadResponse` for file upload. |

## For AI Agents

### Working In This Directory
- **This is the source of truth for JSON shapes.** When you edit a model, update its
  producer (pipeline/tasks) **and** its consumer — including
  `portal/app/scripts/[jobId]/lib/types.ts`, which hand-mirrors `ScriptResponse` /
  `ProgressEvent`.
- Pydantic v2 idioms: prefer `model_copy(update=...)` for edits, `model_dump()` for JSON.
  Serialize with `ensure_ascii=False` so Korean text stays readable in artifacts.
- Keep fields explicit and defaulted where optional (e.g. `needs_review=False`) so older
  on-disk artifacts still validate.

### Testing Requirements
- Schema validation is exercised in `tests/test_token_overlap.py`, `tests/test_script_tasks.py`
  (`TestScriptSchemas`), and the API tests.

### Common Patterns
- Models are plain data (no behavior). Derived/computed values live in the pipeline.

## Dependencies

### Internal
- Imported almost everywhere (`pipeline/`, `tasks/`, `api/`, `demo/`).

### External
- Pydantic v2 (bundled with FastAPI).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
