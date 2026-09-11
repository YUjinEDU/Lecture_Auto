<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# portal — Next.js integration (drop-in)

## Purpose
The lecture-specific **pages and components for the lab's existing Next.js 15 portal** —
not a standalone app (there is no tracked `package.json`/`next.config` here; these files
are meant to be copied into the established portal repo). It implements the two
human-review surfaces of the pipeline:

1. **Script review** (`app/scripts/[jobId]/`) — edit generated scripts per slide, watch
   live generation progress over SSE, then approve to kick off TTS.
2. **TTS review** (`app/lectures/[jobId]/tts/`) — record/clone a voice, preview per-slide
   audio, watch TTS progress, and download the final package.

All data flows through a **same-origin reverse proxy** (`app/api/gpu/[...path]/route.ts`):
the browser calls `/api/gpu/*`, and the homepage's NAS Node server forwards it to the
internal GPU FastAPI server at the server-only `GPU_API_URL`. The GPU box is never exposed
to the browser or the public internet.

## Key Files
| File | Description |
|------|-------------|
| `app/lectures/[jobId]/tts/page.tsx` | `TTSReviewPage` — the TTS review screen: voice registration, per-slide audio preview, SSE TTS progress, package download. Composes the `components/lecture/` widgets. |

## Subdirectories
| Directory | Purpose |
|-----------|---------|
| `app/scripts/[jobId]/` | Script-review route: page + its components/hooks/lib (see `app/scripts/[jobId]/AGENTS.md`). |
| `components/lecture/` | Reusable lecture widgets for the TTS page: recorder, audio preview, progress, download (see `components/lecture/AGENTS.md`). |

> `app/`, `app/lectures/`, `app/lectures/[jobId]/`, `app/lectures/[jobId]/tts/`, and
> `app/scripts/` are route-segment containers with no own AGENTS.md; their only meaningful
> file is the TTS page listed above (the rest is documented in the subdirectories).

## For AI Agents

### Working In This Directory
- These are **App Router client components** (`"use client"`). Routes are dynamic on
  `[jobId]` — read it from the route params.
- All backend calls go to the relative `/api/gpu/*` proxy (base `"/api/gpu"`), never to the
  GPU server directly. The real GPU address lives only in the server-only `GPU_API_URL` env
  (no `NEXT_PUBLIC_`). ⚠️ The homepage auth middleware MUST gate `/api/gpu/*` or it becomes
  an open relay to the whole GPU API.
- Progress is **SSE** (`EventSource`), one-way. Match the backend event shape in
  `app/scripts/[jobId]/lib/types.ts` (`ProgressEvent`).
- The TypeScript types here must stay in sync with `lecture_auto/schemas/` on the backend.

### Testing Requirements
- No JS test harness is committed in this slice; verify against a running FastAPI server.
  When integrated into the portal, follow that repo's test conventions.

### Common Patterns
- Debounced autosave on blur / Ctrl-S (see `ScriptEditor`), optimistic local state, then
  PUT to the API.
- Confirm dialogs gate destructive/expensive actions (regenerate, approve).

## Dependencies

### Internal
- Consumes the FastAPI routes in `lecture_auto/api/routes/` (scripts, tts, download, jobs).

### External
- React 18 / Next.js 15 (App Router), Tailwind utility classes, browser `EventSource` +
  `MediaRecorder` (voice capture).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
