---
phase: 03-script-ui
plan: 03
subsystem: ui
tags: [nextjs, react, tailwind, sse, typescript, script-editor]

# Dependency graph
requires:
  - phase: 03-02
    provides: "FastAPI script routes (CRUD, regenerate, approve, SSE progress, slide PNG)"
provides:
  - "Next.js 2-panel script review page at /scripts/[jobId]"
  - "API client for script CRUD, regenerate, approve endpoints"
  - "SSE hook for real-time script generation progress"
  - "useScripts hook for local state management with optimistic updates"
  - "UI components: SlideListPanel, SlidePreview, ScriptEditor, ActionBar, ProgressFooter, RegenerateConfirmDialog, ApproveConfirmDialog"
affects: [04-tts-pipeline, 05-integration]

# Tech tracking
tech-stack:
  added: [next.js-app-router, tailwind-css, EventSource-SSE]
  patterns: [two-panel-split-layout, optimistic-update, auto-save-on-blur, sse-progress-hook, confirmation-dialog-pattern]

key-files:
  created:
    - portal/app/scripts/[jobId]/page.tsx
    - portal/app/scripts/[jobId]/components/SlideListPanel.tsx
    - portal/app/scripts/[jobId]/components/SlidePreview.tsx
    - portal/app/scripts/[jobId]/components/ScriptEditor.tsx
    - portal/app/scripts/[jobId]/components/ActionBar.tsx
    - portal/app/scripts/[jobId]/components/ProgressFooter.tsx
    - portal/app/scripts/[jobId]/components/RegenerateConfirmDialog.tsx
    - portal/app/scripts/[jobId]/components/ApproveConfirmDialog.tsx
    - portal/app/scripts/[jobId]/hooks/useScripts.ts
    - portal/app/scripts/[jobId]/hooks/useSSEProgress.ts
    - portal/app/scripts/[jobId]/lib/api.ts
    - portal/app/scripts/[jobId]/lib/types.ts
  modified: []

key-decisions:
  - "Direct GPU API calls from Next.js client (not proxied through Next.js API routes) for real-time SSE and lower latency"
  - "NEXT_PUBLIC_GPU_API_URL env var for configurable GPU server base URL"
  - "Auto-save on blur with Ctrl+S shortcut for professor-friendly editing experience"
  - "Confirmation dialogs for destructive actions (regenerate edited scripts, approve all for TTS)"

patterns-established:
  - "Two-panel layout: 240px fixed left panel + flex-1 right panel with responsive breakpoints"
  - "SSE hook pattern: EventSource with retry (max 3, 3s delay), auto-cleanup on unmount"
  - "Optimistic update: updateLocal() modifies local state immediately, API call in background"
  - "Confirmation dialog pattern: modal overlay with cancel + destructive/primary action"

requirements-completed: [UI-01, UI-02, UI-03, UI-05]

# Metrics
duration: 25min
completed: 2026-03-30
---

# Phase 03 Plan 03: Script Review UI Summary

**Next.js 2-panel script review page with slide thumbnails, inline script editor with auto-save, SSE progress bar, and regenerate/approve workflows**

## Performance

- **Duration:** 25 min
- **Started:** 2026-03-30T07:30:00Z
- **Completed:** 2026-03-30T07:55:00Z
- **Tasks:** 3 (2 auto + 1 human-verify checkpoint)
- **Files created:** 12

## Accomplishments
- Built complete 2-panel script review UI matching UI-SPEC contract (240px slide list + flex-1 editor)
- Implemented data layer: TypeScript types, API client (5 endpoints + 2 URL helpers), SSE progress hook with retry, useScripts hook with optimistic updates
- All 8 UI components built with Tailwind CSS: SlideListPanel, SlidePreview, ScriptEditor, ActionBar, ProgressFooter, RegenerateConfirmDialog, ApproveConfirmDialog, and main page
- Human verification passed: professor confirmed 2-panel layout, slide navigation, script editing/saving, regeneration/approval dialogs, and live API integration

## Task Commits

Each task was committed atomically:

1. **Task 1: Types, API client, and hooks** - `efeb729` (feat)
2. **Task 2: UI components and page assembly per UI-SPEC** - `ac2dab4` (feat)
3. **Task 3: Visual verification (human-verify checkpoint)** - approved by user, no commit needed

## Files Created/Modified
- `portal/app/scripts/[jobId]/lib/types.ts` - ScriptResponse, ProgressEvent, SlideStatus types
- `portal/app/scripts/[jobId]/lib/api.ts` - API client: fetchScripts, updateScript, regenerateScript, approveScripts, getSlideImageUrl, getProgressUrl
- `portal/app/scripts/[jobId]/hooks/useSSEProgress.ts` - EventSource hook with retry logic (max 3, 3s delay)
- `portal/app/scripts/[jobId]/hooks/useScripts.ts` - Script state management with optimistic local updates
- `portal/app/scripts/[jobId]/components/SlideListPanel.tsx` - Left panel with scrollable slide thumbnails and status badges
- `portal/app/scripts/[jobId]/components/SlidePreview.tsx` - Slide image preview with object-contain scaling
- `portal/app/scripts/[jobId]/components/ScriptEditor.tsx` - Textarea editor with auto-save on blur and Ctrl+S
- `portal/app/scripts/[jobId]/components/ActionBar.tsx` - Regenerate and Save action buttons
- `portal/app/scripts/[jobId]/components/ProgressFooter.tsx` - Sticky footer with progress bar and Approve button
- `portal/app/scripts/[jobId]/components/RegenerateConfirmDialog.tsx` - Confirmation dialog for overwriting edited scripts
- `portal/app/scripts/[jobId]/components/ApproveConfirmDialog.tsx` - Confirmation dialog for starting TTS generation
- `portal/app/scripts/[jobId]/page.tsx` - Main page assembling all components with 2-panel layout

## Decisions Made
- Direct GPU API calls from client side (NEXT_PUBLIC_GPU_API_URL) -- avoids Next.js API route timeout limits and enables native SSE
- Auto-save on blur with visual feedback ("Saving..." / "Saved") -- matches professor workflow expectation
- Responsive breakpoints: dropdown at <768px, narrower panel at <1024px -- accommodates various screen sizes

## Deviations from Plan

None from executor -- plan executed exactly as written.

### Issues Found During Human Verification

User found and fixed 2 bugs during portal integration testing (fixes applied by user directly in portal repo):

1. **useMemo side effect violation** - React rules violation where useMemo was used for a side effect; user fixed by converting to useEffect
2. **"Saved" indicator not showing** - onChange handler was not connected to track dirty state; user fixed by wiring onChange

These were integration-time fixes in the user's portal repo, not in the plan's output files.

## Issues Encountered
None during automated execution.

## User Setup Required
None - no external service configuration required. The portal files are ready to be integrated into the existing Next.js portal with `NEXT_PUBLIC_GPU_API_URL` environment variable set.

## Known Stubs
None - all components are fully wired to API endpoints with real data flow. No placeholder data or TODO markers.

## Next Phase Readiness
- Script review UI complete, ready for TTS pipeline integration (Phase 04)
- Approve button triggers `approveScripts()` API call which returns `tts_task_id` -- Phase 04 will implement the TTS task that this triggers
- SSE progress infrastructure can be extended for TTS progress events

## Self-Check: PASSED

- All 12 files verified present on disk
- Commit efeb729 (Task 1) verified in git log
- Commit ac2dab4 (Task 2) verified in git log

---
*Phase: 03-script-ui*
*Completed: 2026-03-30*
