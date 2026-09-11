<!-- Parent: ../../../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# scripts/[jobId] — script review route

## Purpose
The script-review screen. `ScriptReviewPage` lets the professor step through slides, edit
each generated script with autosave, watch live generation progress over SSE, regenerate a
single slide, and finally approve the whole deck (which hands off to TTS). This folder also
contains the route's **hooks** (data + progress) and **lib** (API client + types); the
presentational pieces live in `components/`.

## Key Files
| File | Description |
|------|-------------|
| `page.tsx` | `ScriptReviewPage` — composes the slide list, preview, editor, progress footer, and confirm dialogs into the review flow. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `components/` | Presentational components for this route (see `components/AGENTS.md`). |
| `hooks/` | `useScripts.ts` (fetch + local cache of slide scripts) and `useSSEProgress.ts` (subscribe to the generation progress `EventSource`). *No separate AGENTS.md — documented here.* |
| `lib/` | `api.ts` (typed fetch wrappers: `fetchScripts`/`updateScript`/`regenerateScript`/`approveScripts` + `getSlideImageUrl`/`getProgressUrl`) and `types.ts` (`ScriptResponse`, `ProgressEvent`, `SlideStatus`). *No separate AGENTS.md — documented here.* |

## For AI Agents

### Working In This Directory
- **All backend access goes through `lib/api.ts`.** Its base is `"/api/gpu"` (the same-origin
  proxy), so calls hit the homepage and are forwarded server-side to the internal GPU API —
  don't `fetch` the GPU server directly from components.
- `lib/types.ts` **hand-mirrors** `lecture_auto/schemas/script.py` and `job_status.py`.
  When the backend models change, update these types in lockstep.
- Progress is read-only SSE via `useSSEProgress`; `useScripts` owns the slide data and
  optimistic local edits. Keep data/effect logic in hooks, rendering in `components/`.
- Approve is gated on all scripts being non-empty (`allNonEmpty`) — preserve that guard.

### Testing Requirements
- No JS tests committed in this slice; verify against a running FastAPI server. The backend
  contract is covered by `tests/test_scripts_api.py`.

### Common Patterns
- Debounced autosave (blur + Ctrl/Cmd-S) with `idle/saving/saved` status (see
  `components/ScriptEditor.tsx`).
- `SlideStatus` (`generating|generated|edited|empty|error`) drives the slide list styling.

## Dependencies

### Internal
- FastAPI routes in `lecture_auto/api/routes/scripts.py` (CRUD/regenerate/approve/progress/PNG).

### External
- React 18 / Next.js 15 client components, browser `EventSource`, Tailwind classes.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
