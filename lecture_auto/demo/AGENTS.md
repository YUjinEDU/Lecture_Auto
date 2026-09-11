<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# demo — self-contained local workflow

## Purpose
A presentation-friendly driver that runs the whole flow **on one machine without GPU or
Redis**. Where `tasks/` uses Celery + Qwen models, `demo/` orchestrates the stages
in-process and degrades gracefully through **CPU TTS fallbacks** (flite, a local Korean
synth) so a demo always produces output. It keeps job state in memory plus JSON snapshots
on disk, supports stop/cancel, and exposes fine-grained rerun primitives (re-TTS only,
re-video only, rebuild after a script edit).

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Demo package doc. |
| `state.py` | `DemoJob` dataclass + in-memory registry (`create_job`/`get_job`/`list_jobs`/`list_job_summaries`/`delete_job`/`rename_job`) and stage tracking. |
| `jobs.py` | Disk persistence: job snapshots (save/load), uploaded-PDF + voice-reference saving, versioned "library" artifacts (`_add_version_entry`, `_refresh_library_artifacts`). |
| `orchestration.py` | The driver: `run_demo_pipeline` / `launch_demo_pipeline`, plus reruns — `update_script_and_rebuild`, `update_glossary`, `rerun_tts_only`, `rerun_video_only`, `rerun_scripts_and_media`, `launch_rerun`. |
| `synthesis.py` | Media stages with fallbacks: `_render_script_stage`, `_run_tts_loop` (Qwen → flite → local-Korean), `_assemble_final_video`, `_render_media_stage`. |
| `ai.py` | Korean-language text shaping for demo scripts: line normalization, Hangul/noise scoring, title/body/keyword extraction, evidence payloads, glossary application. |
| `control.py` | Cooperative cancellation: `request_stop()` sets a flag; `_check_stop()` raises at the next stage checkpoint. |

## For AI Agents

### Working In This Directory
- This layer **may** sequence and persist (unlike `pipeline/`), but it should still call
  the shared `pipeline/` stages where possible rather than forking their logic.
- **Fallbacks are the point.** Don't make a stage hard-require a GPU model; chain to the
  CPU path so the demo never dead-ends.
- Long runs must poll `control._check_stop()` at stage boundaries so Stop works promptly.
- Reruns are granular — reuse existing artifacts and only rebuild the requested stage(s).

### Testing Requirements
- See `tests/demo/` (e.g. approve endpoint + slide status behavior).

### Common Patterns
- In-memory `DemoJob` mirrored to a JSON snapshot; the library keeps versioned outputs.
- Glossary is editable and re-applied on rebuild for consistent terminology.

## Dependencies

### Internal
- `pipeline/` (parse/render/vlm), `schemas/`, `storage/`. Surfaced via `api/routes/demo.py`
  and the `demo_static/` UI.

### External
- flite / local Korean TTS (CPU fallbacks), ffmpeg, soundfile.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
