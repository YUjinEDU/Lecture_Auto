<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-13 | Updated: 2026-06-13 -->

# demo_static — demo single-page UI

## Purpose
A dependency-free **vanilla HTML/CSS/JS** front end for the demo workflow, served directly
by FastAPI (`api/main.py` mounts it with no-cache during development) and driven by the
`api/routes/demo.py` endpoints. This is the all-in-one screen the professor uses in a live
demo — separate from the production `portal/` (Next.js) integration.

## Key Files
| File | Description |
|------|-------------|
| `index.html` | App shell (title "Lecture Auto"); single-screen layout for upload → review → audio/video. |
| `app.js` | All client logic (~46 KB): state management, API calls to the demo routes, SSE/polling progress, script editing, voice recording, rerun controls. |
| `styles.css` | Full styling (~42 KB): glassmorphism cards, gradient background, sidebar, responsive layout. |

## For AI Agents

### Working In This Directory
- **No build step, no framework, no npm.** Keep it vanilla — plain DOM APIs and `fetch`.
  Don't introduce a bundler or React here; that's what `portal/` is for.
- Talk only to the demo routes (`/demo/...`); the production portal uses the typed
  `scripts`/`tts`/`download` routes instead.
- It's served with caching disabled in dev — hard-refresh after edits if testing manually.

### Testing Requirements
- No automated front-end tests; verify in a browser against a running FastAPI server.

### Common Patterns
- A single `State` object at the top of `app.js`; render functions read from it.

## Dependencies

### Internal
- `api/routes/demo.py` (backend) + `demo/` orchestration behind it.

### External
- None (browser built-ins only).

<!-- MANUAL: Any manually added notes below this line are preserved on regeneration -->
