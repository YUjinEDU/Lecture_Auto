<!-- Parent: ../../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# components/lecture — TTS-review widgets

## Purpose
Reusable client components for the TTS review screen (`app/lectures/[jobId]/tts/page.tsx`):
capture/clone a voice, preview per-slide audio, watch TTS progress, and download the final
package. Unlike the script-route components, these live at the portal level so they can be
shared across lecture pages.

## Key Files
| File | Description |
|------|-------------|
| `VoiceRecorder.tsx` | Records a short voice sample via the browser `MediaRecorder` for voice cloning, then uploads it as the professor's voice reference. |
| `AudioPreview.tsx` | Plays a single slide's synthesized WAV for review. |
| `TTSProgressFooter.tsx` | Sticky footer showing per-slide TTS generation progress (SSE). |
| `DownloadPackage.tsx` | Lists the deliverables and triggers the streaming ZIP download. |

## For AI Agents

### Working In This Directory
- Backend access targets the `tts` and `download` routes
  (`lecture_auto/api/routes/tts.py`, `download.py`) via the same-origin `/api/gpu` proxy
  (base `"/api/gpu"`), never the GPU host directly.
- `VoiceRecorder` produces **WebM** from `MediaRecorder`; the backend converts it to WAV
  (`storage/voice_store.py::convert_webm_to_wav`) — send the blob as-is, don't pre-convert
  in the browser.
- TTS progress is read-only SSE, same `ProgressEvent` shape as the script side.

### Testing Requirements
- No committed JS tests; verify with a running backend + a microphone-capable browser.
  Backend contract: `tests/test_*` for tts/download routes (where present).

### Common Patterns
- `"use client"`; request mic permission lazily on first record; Tailwind + inline SVG.

## Dependencies

### Internal
- `lecture_auto/api/routes/tts.py` (register/preview/progress) and `download.py` (package).

### External
- React 18, browser `MediaRecorder` + `EventSource`.

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
