<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# components — script-review UI pieces

## Purpose
Presentational client components composed by `ScriptReviewPage`. They render slides, the
editor, progress, and the confirm dialogs; they hold local UI state but delegate all data
fetching/mutation to the route's hooks and `lib/api.ts`.

## Key Files
| File | Description |
|------|-------------|
| `SlideListPanel.tsx` | Left rail listing every slide with its `SlideStatus` styling; selects the active slide. |
| `SlidePreview.tsx` | Renders the active slide PNG via `getSlideImageUrl` (thin `<img>` wrapper). |
| `ScriptEditor.tsx` | Editable `<textarea>` with debounced autosave on blur + Ctrl/Cmd-S, showing `Saving…`/`Saved` status; read-only when disabled. |
| `ProgressFooter.tsx` | Sticky bottom bar: generation progress bar (`current/total`) and the Approve button, enabled only when all scripts are non-empty. |
| `ActionBar.tsx` | Per-slide action row (e.g. regenerate trigger). |
| `ApproveConfirmDialog.tsx` | Confirmation modal before approving the whole deck → TTS. |
| `RegenerateConfirmDialog.tsx` | Confirmation modal before regenerating a single slide's script. |

## For AI Agents

### Working In This Directory
- Keep components **presentational**: take data + callbacks as props; don't `fetch` here.
  Side effects and API calls belong in the route's `hooks/` and `lib/api.ts`.
- Mirror the editor's save contract: call `onSave(text)` and surface the `saving/saved`
  status; don't bypass the debounce.
- Gate expensive/irreversible actions (approve, regenerate) behind the confirm dialogs.

### Testing Requirements
- No committed JS tests; verify visually against a running backend.

### Common Patterns
- `"use client"` components; Tailwind utility classes; inline SVG icons (no icon dep).
- Status-driven styling keyed off `SlideStatus` from `../lib/types`.

## Dependencies

### Internal
- `../lib/types` (`ScriptResponse`, `ProgressEvent`, `SlideStatus`), `../lib/api` (URLs).

### External
- React 18.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
