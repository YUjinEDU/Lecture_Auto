<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# storage — filesystem layout & voice files

## Purpose
Owns the **per-job directory convention** and voice-reference persistence. All layers
locate artifacts through here instead of hardcoding paths, which is also the seam the API
tests mock. Local disk is intentional (GPU-local I/O is the pipeline hot path; see
`CLAUDE.md` — Supabase Storage is only for final artifact URLs).

## Key Files
| File | Description |
|------|-------------|
| `__init__.py` | Storage package marker. |
| `jobs.py` | `JobPaths` — resolves a job's `input/parsed/vlm/scripts/audio/...` subdirectories under the job root. The single source of truth for where artifacts live. |
| `voice_store.py` | Per-professor voice references: `save_voice_ref()`, `get_voice_ref()`, and `convert_webm_to_wav()` (browser recordings → WAV via ffmpeg). |

## For AI Agents

### Working In This Directory
- **Route every path through `JobPaths`.** New artifact types get a property here, not an
  inline `Path(...)` join elsewhere — that keeps the API mockable and the layout in one place.
- Browser recordings arrive as WebM; convert to WAV before TTS uses them as a voice ref.
- Keep `data/` ephemeral and reproducible — nothing here should be the only copy of state.

### Testing Requirements
- API tests inject a mock `JobPaths` pointing at `tmp_path`; preserve that constructor shape.

### Common Patterns
- `pathlib.Path` everywhere (per `CLAUDE.md` convention), never `os.path`.

## Dependencies

### Internal
- Used by `api/routes/`, `tasks/`, and `demo/` to locate per-job files.

### External
- ffmpeg (WebM→WAV conversion).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
