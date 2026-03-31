---
phase: 04-tts-delivery
plan: 03
subsystem: ui
tags: [next.js, react, tts, mediarecorder, sse, audio, voice-clone, zip-download]

# Dependency graph
requires:
  - phase: 04-02
    provides: TTS API routes (voice/register, audio playback, regenerate, package download, SSE progress)
  - phase: 03-script-ui
    provides: UI design system (03-UI-SPEC.md), 2-panel layout pattern, SSE progress footer pattern
provides:
  - TTS review page at /lectures/[jobId]/tts with full audio workflow
  - VoiceRecorder component (browser MediaRecorder + WAV file upload)
  - AudioPreview component (per-slide HTML5 audio playback + re-TTS)
  - DownloadPackage component (ZIP download with package info)
  - TTSProgressFooter component (SSE-driven TTS progress bar)
affects: [05-integration, portal-deployment]

# Tech tracking
tech-stack:
  added: [MediaRecorder API, EventSource SSE, HTML5 Audio]
  patterns: [browser-voice-recording, sse-progress-footer, 2-panel-audio-review]

key-files:
  created:
    - portal/components/lecture/VoiceRecorder.tsx
    - portal/components/lecture/AudioPreview.tsx
    - portal/components/lecture/DownloadPackage.tsx
    - portal/components/lecture/TTSProgressFooter.tsx
    - portal/app/lectures/[jobId]/tts/page.tsx
  modified: []

key-decisions:
  - "MediaRecorder with audio/webm;codecs=opus for browser recording (best cross-browser support)"
  - "3-second countdown auto-stop for voice clip capture (per D-03 decision)"
  - "HTML5 audio element with controls for per-slide playback (native browser UI, no custom player)"
  - "window.open for ZIP download trigger (avoids fetch blob overhead for large files)"
  - "Reused Phase 3 SSE progress footer pattern for TTS progress consistency"

patterns-established:
  - "Voice recording flow: getUserMedia -> MediaRecorder -> FormData POST"
  - "Audio preview with key-based reload: change React key to force audio element refresh after re-TTS"
  - "2-panel TTS review layout: slide thumbnails (240px) + detail panel with audio controls"

requirements-completed: [TTS-02, TTS-03, UI-04]

# Metrics
duration: 8min
completed: 2026-03-31
---

# Phase 04 Plan 03: TTS Review UI Summary

**Next.js TTS review page with browser voice recording, per-slide audio preview via HTML5 audio, SSE progress footer, and ZIP package download**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-31T11:35:00Z
- **Completed:** 2026-03-31T11:43:44Z
- **Tasks:** 3 (2 auto + 1 human-verify checkpoint)
- **Files created:** 5

## Accomplishments
- VoiceRecorder component supports both browser MediaRecorder recording (3s auto-stop) and WAV file upload with voice/register API integration
- AudioPreview component provides per-slide HTML5 audio playback with single-slide re-TTS regeneration
- TTSProgressFooter reuses Phase 3 SSE pattern for real-time TTS generation progress
- TTS review page assembles all components in a 2-panel layout with voice setup, slide list, detail panel, and download section
- DownloadPackage component triggers ZIP download with file count and size info display

## Task Commits

Each task was committed atomically:

1. **Task 1: VoiceRecorder + AudioPreview + DownloadPackage components** - `a89ccb8` (feat)
2. **Task 2: TTSProgressFooter + TTS review page** - `ea54e0d` (feat)
3. **Task 3: Verify TTS review page UI** - checkpoint:human-verify (approved)

## Files Created/Modified
- `portal/components/lecture/VoiceRecorder.tsx` - Browser voice recording (MediaRecorder) + WAV file upload, posts to voice/register
- `portal/components/lecture/AudioPreview.tsx` - Per-slide HTML5 audio playback with re-TTS regenerate button
- `portal/components/lecture/DownloadPackage.tsx` - ZIP download button with package info (file count, size)
- `portal/components/lecture/TTSProgressFooter.tsx` - SSE-driven progress bar for TTS generation (EventSource)
- `portal/app/lectures/[jobId]/tts/page.tsx` - TTS review page: voice setup, 2-panel slide/audio layout, download

## Decisions Made
- Used MediaRecorder with audio/webm;codecs=opus mime type for best cross-browser recording support
- 3-second auto-stop countdown for voice clip (matches D-03 decision)
- HTML5 native audio controls for playback (no custom audio player needed for MVP)
- window.open approach for ZIP download (avoids loading entire blob into memory)
- Reused exact SSE progress footer pattern from Phase 3 script review for UI consistency

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 04 (tts-delivery) is now complete with all 3 plans delivered
- Full pipeline UI available: upload -> parse -> VLM -> script review -> TTS -> audio review -> download
- Ready for Phase 05 integration testing and deployment preparation
- GPU API endpoints (Phase 04 Plans 01-02) serve as backend for these UI components

## Self-Check: PASSED

- All 5 created files verified present on disk
- Commit a89ccb8 (Task 1) verified in git log
- Commit ea54e0d (Task 2) verified in git log

---
*Phase: 04-tts-delivery*
*Completed: 2026-03-31*
