---
phase: quick-260410-tou
plan: 01
subsystem: demo-pipeline
tags: [refactor, module-split, pipeline]
key-files:
  created:
    - lecture_auto/demo/jobs.py
    - lecture_auto/demo/control.py
    - lecture_auto/demo/ai.py
    - lecture_auto/demo/synthesis.py
    - lecture_auto/demo/orchestration.py
    - lecture_auto/demo/__init__.py
  deleted:
    - lecture_auto/demo/pipeline.py
decisions:
  - "restore_job_from_disk kept in jobs.py with lazy imports of ai/synthesis to avoid circular deps"
  - "_render_script_stage kept in synthesis.py (it orchestrates AI + storage) to avoid circular deps between orchestration and synthesis"
metrics:
  duration: ~15min
  completed: 2026-04-10
  tasks_completed: 2
  files_changed: 7
---

# Quick Task 260410-tou: Split pipeline.py into 5 Modules

**One-liner:** Split 1555-line god-module pipeline.py into 5 focused modules (jobs, control, ai, synthesis, orchestration) with backward-compat __init__.py re-exports.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Extract jobs, control, ai, synthesis | b480bc3 | jobs.py, control.py, ai.py, synthesis.py |
| 2 | Create orchestration.py, update __init__.py, delete pipeline.py | 2b845e3 | orchestration.py, __init__.py, pipeline.py (deleted) |

## Verification Results

- `uv run python3 -c "from lecture_auto.demo import ..."` passes for all public symbols
- `lecture_auto/demo/pipeline.py` does not exist
- `grep -r "from.*pipeline import|import.*pipeline" lecture_auto/demo/` returns no hits
- `python3 -m py_compile` exits 0 for all 5 new modules
- No circular import errors

## Module Sizes

- jobs.py: ~220 lines (job state, persistence, file upload, restore)
- control.py: ~35 lines (stop-flag / thread management)
- ai.py: ~330 lines (GPT VLM + LLM script generation)
- synthesis.py: ~250 lines (TTS synthesis, video assembly, media)
- orchestration.py: ~270 lines (pipeline entry points)

All modules under 350-line target.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Circular import] restore_job_from_disk uses lazy imports for ai/synthesis**
- **Found during:** Task 1 (jobs.py creation)
- **Issue:** jobs.py cannot import from ai.py/synthesis.py at module level because those modules import from jobs.py, creating a circular dependency.
- **Fix:** Used local (lazy) imports inside `restore_job_from_disk` body for `_extract_title`, `_evidence_payload`, `_load_saved_notes`, and state functions.
- **Files modified:** lecture_auto/demo/jobs.py

**2. [Rule 1 - Circular import] _render_script_stage placed in synthesis.py with lazy imports for ai functions**
- **Found during:** Task 1 (synthesis.py creation)
- **Issue:** `_render_script_stage` calls both ai functions and synthesis functions; placing it in orchestration.py would require orchestration to import synthesis + call ai directly, which is fine, but synthesis.py already imports ai.py. Keeping it in synthesis.py with local imports avoids adding another import layer.
- **Fix:** Used local imports inside `_render_script_stage` body for ai module symbols (SCRIPT_BATCH_SIZE, _build_script_slide_payloads, etc.) and datetime.
- **Files modified:** lecture_auto/demo/synthesis.py

## Self-Check: PASSED

- lecture_auto/demo/jobs.py: FOUND
- lecture_auto/demo/control.py: FOUND
- lecture_auto/demo/ai.py: FOUND
- lecture_auto/demo/synthesis.py: FOUND
- lecture_auto/demo/orchestration.py: FOUND
- lecture_auto/demo/__init__.py: FOUND
- lecture_auto/demo/pipeline.py: DELETED (confirmed)
- Commit b480bc3: FOUND
- Commit 2b845e3: FOUND
