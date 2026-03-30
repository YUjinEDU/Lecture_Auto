# Phase 3: Script + UI - Research

**Researched:** 2026-03-30
**Domain:** PDF text extraction (PyMuPDF), Celery script task, FastAPI script routes, Next.js review UI
**Confidence:** HIGH

## Summary

Phase 3 covers four distinct work areas: (1) replacing the python-pptx text parser with PyMuPDF (fitz) for PDF-based text extraction with span-level font metadata, (2) wrapping the existing `script_gen.py` as a Celery task following the established `vlm_tasks.py` pattern, (3) adding FastAPI routes for script CRUD/regeneration, and (4) building a 2-panel review UI in the existing Next.js portal.

The backend work is low-risk because Phase 2 already established all infrastructure patterns (Celery tasks, Redis progress, SSE streaming, FastAPI routes). The script generation logic itself is already implemented in `script_gen.py` from Phase 01.1 -- it just needs to be wrapped as a Celery task with file-based checkpointing and progress publishing. The PyMuPDF parser is a focused replacement of `parser.py` that outputs the same `SlideRecord` schema. The highest-risk area is the Next.js portal UI integration, since no frontend code exists in this repo yet and the portal is an external project.

**Primary recommendation:** Structure the phase in 3-4 plans: (1) PyMuPDF PDF parser replacing python-pptx parser, (2) script Celery task + FastAPI routes, (3) Next.js portal UI page for script review/edit. Keep backend plans independent of the frontend plan so they can be verified separately.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** 2-panel split layout -- left slide list (thumbnails), right selected slide PNG + script edit area
- **D-02:** Click slide in list to switch right panel to that slide
- **D-03:** Per-slide individual "regenerate" button (not batch checkbox)
- **D-04:** Edited scripts protected from regeneration -- track edit status, show confirmation prompt before overwriting edited slides
- **D-05:** Approval = TTS auto-start. "Approve Scripts" button click triggers Phase 4 TTS pipeline
- **D-06:** Approve button only active when all slides have non-empty scripts
- **D-07:** Replace python-pptx text extraction with PyMuPDF (fitz) based parser
- **D-08:** Use PyMuPDF span-level info: y-coordinate top + large font size + bold flags = auto title detection
- **D-09:** pdfplumber as fallback for table slides and parsing anomalies
- **D-10:** Accept both PPTX and PDF as input (PPTX converts via LibreOffice to PDF)
- **D-11:** Speaker notes excluded (consistent with D-05 from Phase 1)

### Claude's Discretion
- Script editor UI detail design (textarea vs rich editor)
- Slide list thumbnail size and layout
- Progress display method (reuse existing SSE pattern)
- Script Celery task internal implementation (follow Phase 2 vlm_tasks.py pattern)
- PyMuPDF to SlideRecord conversion logic details

### Deferred Ideas (OUT OF SCOPE)
- Supabase Auth professor role integration -- separate Phase (INFRA-03)
- Script history/version management -- v2 feature
- Real-time collaborative editing -- Out of Scope
- PyMuPDF Korean bench test -- needs professor's actual slides (pre-implementation verification)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SCRIPT-01 | Combine slide structure + VLM notes via Claude Code for script generation | Existing `script_gen.py` already implements this; wrap as Celery task |
| SCRIPT-02 | Use lecture_context with prev/next slide context in script generation | `build_script_prompt()` already implements context window pattern |
| SCRIPT-03 | Adjust per-slide script length to match target lecture duration | `generate_scripts()` already computes `target_seconds = (target_minutes * 60) / slide_count` |
| SCRIPT-04 | Script output includes slide_id, target_seconds, script, keywords, transition_to_next | `SlideScript` Pydantic model already has all fields |
| UI-01 | Provide lecture automation page within lab portal (Next.js) | New page in existing Next.js portal; 2-panel split layout per D-01 |
| UI-02 | Provide per-slide script review and text editing UI | Right panel with slide PNG + textarea editor per D-01/D-02 |
| UI-03 | Display pipeline progress and stage status in real-time | Reuse existing SSE pattern from Phase 2 (progress.py + EventSourceResponse) |
| UI-05 | Allow selective slide script/audio regeneration | Per-slide regenerate button (D-03) with edit protection (D-04) |
</phase_requirements>

## Standard Stack

### Core (New Dependencies for Phase 3)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PyMuPDF | 1.27.2.2 | PDF text extraction with span-level font metadata | Verified latest on PyPI (2026-03-19). No external deps. Fast C-based PDF parser. |
| pdfplumber | 0.11.9 | Table extraction fallback for table-heavy slides | Verified latest on PyPI. Best Python table-from-PDF extractor. |

### Existing (Already in pyproject.toml)
| Library | Version | Purpose | Phase 3 Role |
|---------|---------|---------|--------------|
| FastAPI | >=0.135.1 | REST API framework | Script CRUD routes, regeneration endpoints |
| Celery[redis] | >=5.4,<6.0 | Async task queue | Script generation task on cpu_queue |
| redis | >=5.0 | Broker + progress pub/sub | Script progress events |
| sse-starlette | >=2.0 | SSE streaming | Script generation progress to frontend |
| pydantic | >=2.0 | Schema validation | Script request/response models |

### Frontend (Next.js Portal -- External Repo)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Next.js | 15.x | Existing lab portal | Already deployed on Vercel |
| EventSource (browser API) | native | SSE client for progress | No library needed; native browser API |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| PyMuPDF | pdfminer.six | Slower, less maintained, no C acceleration |
| pdfplumber (fallback) | camelot-py | Requires ghostscript system dep; pdfplumber is pure Python |
| textarea editor | TipTap/Slate rich editor | Overkill -- professor edits plain lecture text, not formatted HTML |

**New dependencies to add to pyproject.toml:**
```bash
# Add to pyproject.toml dependencies list:
"pymupdf>=1.27",
"pdfplumber>=0.11",
```

## Architecture Patterns

### Recommended Project Structure (Phase 3 Additions)
```
lecture_auto/
  pipeline/
    parser.py            # REPLACE: PyMuPDF-based PDF parser (was python-pptx)
    parser_pptx.py       # KEEP: rename old parser for reference/fallback
    script_gen.py         # KEEP: existing, no changes needed
  tasks/
    vlm_tasks.py          # EXISTING: pattern to follow
    script_tasks.py       # NEW: Celery task wrapping script_gen.py
  api/
    routes/
      jobs.py             # EXISTING: VLM routes
      scripts.py          # NEW: script CRUD + regenerate + approve
  schemas/
    manifest.py           # MODIFY: may need minor updates for PDF-sourced data
    script.py             # NEW: script request/response schemas (or reuse from script_gen.py)
```

### Pattern 1: PyMuPDF PDF Parser (Replacing python-pptx)
**What:** Extract text with font metadata from PDF pages (converted from PPTX via LibreOffice)
**When to use:** Every job -- PPTX is first converted to PDF, then PDF is parsed
**Key API:**
```python
import pymupdf

doc = pymupdf.open(pdf_path)
for page_num, page in enumerate(doc):
    # get_text("dict") returns hierarchical structure:
    # {"blocks": [{"lines": [{"spans": [{"text", "font", "size", "flags", "bbox", "origin", "color"}]}]}]}
    data = page.get_text("dict")
    for block in data["blocks"]:
        if block["type"] == 0:  # text block (type 1 = image)
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"]
                    font_size = span["size"]
                    flags = span["flags"]
                    is_bold = bool(flags & 16)  # TEXT_FONT_BOLD = 16
                    is_italic = bool(flags & 2)  # TEXT_FONT_ITALIC = 2
                    bbox = span["bbox"]  # (x0, y0, x1, y1)
```

**Title Detection Heuristic (D-08):**
```python
def is_title_span(span: dict, page_height: float) -> bool:
    """Detect title using y-position (top quarter) + large font + bold."""
    y_top = span["bbox"][1]
    is_top_quarter = y_top < page_height * 0.25
    is_large = span["size"] >= 18.0  # Typical title font size threshold
    is_bold = bool(span["flags"] & 16)
    return is_top_quarter and (is_large or is_bold)
```

### Pattern 2: Script Celery Task (Following vlm_tasks.py)
**What:** Wrap `generate_scripts()` as a Celery task with checkpointing and progress
**When to use:** After VLM processing completes
**Critical difference from VLM task:** Script generation uses `claude -p` subprocess (CPU-bound, not GPU), so route to a separate `cpu_queue`
```python
@shared_task(
    bind=True,
    name="script.generate_scripts",
    max_retries=2,
    queue="cpu_queue",  # NOT gpu_queue -- claude -p is CPU/network
    acks_late=True,
)
def generate_scripts_task(self, job_id: str) -> dict:
    """Generate scripts with file-based checkpointing.

    Checkpoint: script_{NNN}.json existence = skip.
    Progress: publish_progress(job_id, "script", i+1, total, status).
    Sequential: each slide depends on previous script (SCRIPT-02).
    """
```

### Pattern 3: Script CRUD Routes
**What:** FastAPI routes for script list, update, regenerate, approve
**Endpoints:**
```
GET    /jobs/{job_id}/scripts          -- List all slide scripts
PUT    /jobs/{job_id}/scripts/{slide}  -- Update script text (professor edit)
POST   /jobs/{job_id}/scripts/{slide}/regenerate  -- Regenerate single slide
POST   /jobs/{job_id}/scripts/approve  -- Approve all -> trigger TTS
GET    /jobs/{job_id}/scripts/progress -- SSE stream for script generation
```

### Pattern 4: Edit Protection (D-04)
**What:** Track which scripts the professor has manually edited; protect from overwrite on regenerate
**Implementation:**
```python
# In script JSON on disk, add "edited" field:
{
    "slide_index": 0,
    "slide_number": 1,
    "target_seconds": 120.0,
    "script": "...",
    "keywords": [...],
    "transition_to_next": "...",
    "edited": false,       # NEW: set to true when professor saves edit
    "edited_at": null      # NEW: ISO timestamp of last manual edit
}
```
- PUT endpoint sets `edited=true` + `edited_at` timestamp
- Regenerate endpoint checks `edited` flag; if true, return 409 Conflict unless `?force=true` query param
- Frontend shows confirmation dialog before force-regenerating edited scripts

### Pattern 5: Next.js SSE Client (Frontend)
**What:** Connect to FastAPI SSE endpoint from Next.js client component
**Key considerations:**
- Next.js on Vercel cannot do long-lived SSE proxying (10-60s timeout)
- Frontend must connect DIRECTLY to GPU server FastAPI SSE endpoint
- Use browser-native EventSource API
```typescript
// Client component
'use client';
const eventSource = new EventSource(
  `${GPU_API_URL}/jobs/${jobId}/scripts/progress`
);
eventSource.addEventListener('progress', (e) => {
  const data = JSON.parse(e.data);
  setProgress(data);
});
eventSource.addEventListener('complete', () => {
  eventSource.close();
  fetchScripts(); // Reload final scripts
});
```

### Anti-Patterns to Avoid
- **Proxying SSE through Next.js API Routes:** Vercel has 10-60s function timeout limits. The frontend MUST connect directly to the GPU server's FastAPI SSE endpoint, not through a Next.js proxy route.
- **Running script generation on gpu_queue:** `claude -p` is a subprocess that does not need GPU. Running it on `gpu_queue` with `concurrency=1` would block VLM/TTS tasks. Use a separate `cpu_queue`.
- **Parallel script generation:** Each slide's script depends on the previous slide's script for context (SCRIPT-02). Generation MUST be sequential.
- **Mutating SlideScript after generation:** Follow immutability pattern. Professor edits create a new JSON file (with `edited=true`), not mutate in place. Regeneration writes a fresh file.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PDF text extraction | Custom PDF binary parser | PyMuPDF `page.get_text("dict")` | PDF spec is 1000+ pages; PyMuPDF handles all edge cases |
| Table extraction from PDF | Regex-based table detection | pdfplumber `page.extract_tables()` | Table detection requires spatial reasoning; pdfplumber's heuristics are battle-tested |
| Font property detection | Manual TTF/OTF flag parsing | PyMuPDF span `flags` bitmask | MuPDF C library already parses font programs |
| SSE server | Custom chunked response handler | sse-starlette `EventSourceResponse` | Already used in Phase 2; handles keep-alive, formatting |
| SSE client | Custom fetch + ReadableStream parser | Browser `EventSource` API | Native API handles reconnection, event parsing |
| Celery task routing | Custom queue dispatcher | Celery `task_routes` config + `--queues` flag | Built-in routing is production-proven |

**Key insight:** Nearly every backend component for this phase is either already built (script_gen.py, progress.py, SSE pattern) or is a direct copy of an existing pattern (vlm_tasks.py -> script_tasks.py, jobs.py routes -> scripts.py routes). The only genuinely new code is (a) the PyMuPDF parser and (b) the Next.js UI page.

## Common Pitfalls

### Pitfall 1: PyMuPDF Font Flags Unreliability
**What goes wrong:** Font `flags` field reports incorrect bold/italic status because the font program itself contains wrong metadata.
**Why it happens:** PyMuPDF docs explicitly warn: "this information is not necessarily correct or complete as fonts often contain wrong data."
**How to avoid:** Use font flags as a heuristic, not as ground truth. Combine with font size threshold and y-position for title detection (D-08). Also check font name for "Bold" substring as secondary signal.
**Warning signs:** Titles not detected on certain PDF templates; all text flagged as bold.

### Pitfall 2: `claude -p` Subprocess Timeout
**What goes wrong:** `claude -p` hangs or takes very long for complex slides, causing Celery task timeout.
**Why it happens:** Claude CLI has no built-in timeout; complex prompts with large context windows may take 30-60+ seconds.
**How to avoid:** Set an explicit timeout on `asyncio.wait_for(call_claude(prompt), timeout=120)`. Add retry logic in the Celery task. Consider that `script_gen.py` uses `asyncio.create_subprocess_exec` but Celery tasks are synchronous -- need to bridge with `asyncio.run()` or `loop.run_until_complete()`.
**Warning signs:** Task stays in "processing" state for >5 minutes on a single slide.

### Pitfall 3: Async/Sync Bridge in Celery Task
**What goes wrong:** `script_gen.py` uses `async def generate_scripts()` and `async def call_claude()`, but Celery tasks are synchronous.
**Why it happens:** Celery workers use the prefork pool which doesn't run an event loop.
**How to avoid:** Use `asyncio.run(generate_scripts(...))` inside the Celery task, or refactor `call_claude()` to have a sync variant using `subprocess.run()` instead of `asyncio.create_subprocess_exec`. The sync approach is simpler since script generation is sequential anyway.
**Warning signs:** `RuntimeError: no running event loop` or `RuntimeError: This event loop is already running`.

### Pitfall 4: Vercel SSE Timeout
**What goes wrong:** Next.js API route proxying SSE from FastAPI times out after 10-60 seconds.
**Why it happens:** Vercel serverless functions have hard timeout limits.
**How to avoid:** Frontend connects DIRECTLY to GPU server FastAPI endpoint. CORS is already configured with `allow_origins=["*"]` in `main.py`. Do NOT proxy SSE through Next.js API routes.
**Warning signs:** SSE connection drops after exactly 10s or 60s.

### Pitfall 5: PDF Page-to-Slide Number Mismatch
**What goes wrong:** LibreOffice PDF conversion may add/skip pages (e.g., hidden slides, notes pages).
**Why it happens:** PPTX hidden slides or print settings may affect PDF output.
**How to avoid:** After PDF conversion, verify `len(doc)` matches expected slide count from PPTX. If mismatch, log warning and use PDF page count as authoritative source. The rendered PNGs (from Phase 1 renderer) already use LibreOffice output, so they should be consistent.
**Warning signs:** `manifest.slide_count != len(pdf_doc)`.

### Pitfall 6: Script File Checkpoint Race Condition
**What goes wrong:** Partial `script_NNN.json` written to disk during crash, detected as valid checkpoint on resume.
**Why it happens:** File write is not atomic.
**How to avoid:** Write to a temp file first, then `os.rename()` (atomic on same filesystem). Same pattern should have been used in VLM tasks.
**Warning signs:** Resuming produces `json.JSONDecodeError` on checkpoint files.

### Pitfall 7: Edited Script Lost on Full Regeneration
**What goes wrong:** Professor edits slide 5's script, then triggers "regenerate all" -- slide 5's edit is overwritten.
**Why it happens:** Generate-all doesn't check per-slide `edited` flag.
**How to avoid:** Regenerate-all skips slides with `edited=true` unless explicitly force-overridden. The approval endpoint validates all slides have non-empty scripts (D-06).
**Warning signs:** Professor complaints about lost edits.

## Code Examples

### PyMuPDF PDF Parser -> SlideRecord Conversion
```python
# Source: PyMuPDF docs (https://pymupdf.readthedocs.io/en/latest/app1.html)
import pymupdf
from lecture_auto.schemas.manifest import (
    FontInfo, ShapeRecord, SlideRecord, TextParagraph, TextRun,
)

def parse_pdf(pdf_path: str) -> list[SlideRecord]:
    """Parse PDF into SlideRecord list, replacing python-pptx parser."""
    doc = pymupdf.open(pdf_path)
    slides: list[SlideRecord] = []

    for page_num, page in enumerate(doc):
        data = page.get_text("dict")
        page_height = page.rect.height
        shapes: list[ShapeRecord] = []

        for z_order, block in enumerate(data["blocks"]):
            if block["type"] == 0:  # text block
                paragraphs: list[TextParagraph] = []
                is_title = False

                for line in block["lines"]:
                    runs: list[TextRun] = []
                    for span in line["spans"]:
                        font_info = FontInfo(
                            name=span["font"],
                            size_pt=round(span["size"], 1),
                            bold=bool(span["flags"] & 16),
                            italic=bool(span["flags"] & 2),
                        )
                        runs.append(TextRun(text=span["text"], font=font_info))

                        # Title heuristic (D-08)
                        if (span["bbox"][1] < page_height * 0.25
                                and (span["size"] >= 18.0 or bool(span["flags"] & 16))):
                            is_title = True

                    if runs:
                        full_text = "".join(r.text for r in runs)
                        paragraphs.append(TextParagraph(runs=runs, full_text=full_text))

                bbox = block["bbox"]  # (x0, y0, x1, y1)
                shapes.append(ShapeRecord(
                    shape_id=z_order,
                    name=f"block_{z_order}",
                    z_order=z_order,
                    left=int(bbox[0] * 12700),   # Convert pts to EMU
                    top=int(bbox[1] * 12700),
                    width=int((bbox[2] - bbox[0]) * 12700),
                    height=int((bbox[3] - bbox[1]) * 12700),
                    content_source="text",
                    has_text=True,
                    text_role="title" if is_title else "body",
                    paragraphs=paragraphs,
                ))
            elif block["type"] == 1:  # image block
                bbox = block["bbox"]
                shapes.append(ShapeRecord(
                    shape_id=z_order,
                    name=f"image_{z_order}",
                    z_order=z_order,
                    left=int(bbox[0] * 12700),
                    top=int(bbox[1] * 12700),
                    width=int((bbox[2] - bbox[0]) * 12700),
                    height=int((bbox[3] - bbox[1]) * 12700),
                    content_source="image",
                    has_image=True,
                ))

        slides.append(SlideRecord(
            slide_index=page_num,
            slide_number=page_num + 1,
            png_path=f"slide_{page_num + 1:03d}.png",
            shapes=shapes,
        ))

    doc.close()
    return slides
```

### pdfplumber Table Fallback
```python
# Source: pdfplumber GitHub (https://github.com/jsvine/pdfplumber)
import pdfplumber

def extract_tables_fallback(pdf_path: str, page_num: int) -> list[list[list[str]]]:
    """Extract tables from a specific PDF page using pdfplumber."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_num]
        tables = page.extract_tables()
        return tables if tables else []
```

### Script Celery Task (Sync Wrapper)
```python
# Pattern from: vlm_tasks.py (existing Phase 2 code)
import asyncio
import json
from celery import shared_task
from lecture_auto.tasks.progress import publish_progress

@shared_task(bind=True, name="script.generate", queue="cpu_queue",
             max_retries=2, acks_late=True)
def generate_scripts_task(self, job_id: str) -> dict:
    from lecture_auto.pipeline.script_gen import generate_scripts, SlideScript
    from lecture_auto.schemas.manifest import SlideManifest
    from lecture_auto.storage.jobs import JobPaths

    job_paths = JobPaths(job_id)
    manifest = SlideManifest.model_validate_json(
        job_paths.manifest_path.read_text()
    )

    # Load VLM notes
    vlm_notes = []
    for slide in manifest.slides:
        note_path = job_paths.vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"
        vlm_notes.append(json.loads(note_path.read_text()) if note_path.exists() else {})

    # Run async generate_scripts in sync context
    scripts = asyncio.run(generate_scripts(
        slides=manifest.slides,
        vlm_notes=vlm_notes,
        manifest=manifest,
        scripts_dir=job_paths.scripts_dir,
    ))

    publish_progress(job_id, "script", len(scripts), len(scripts), "done")
    return {"job_id": job_id, "total": len(scripts)}
```

### Script Edit Protection Endpoint
```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

class ScriptUpdateRequest(BaseModel):
    script: str
    keywords: list[str] | None = None
    transition_to_next: str | None = None

@router.put("/{job_id}/scripts/{slide_number}")
async def update_script(job_id: str, slide_number: int, body: ScriptUpdateRequest):
    """Professor edits a slide script. Sets edited=true."""
    script_path = job_paths.scripts_dir / f"script_{slide_number:03d}.json"
    if not script_path.exists():
        raise HTTPException(404, "Script not found")

    data = json.loads(script_path.read_text())
    # Immutable update: create new dict
    updated = {
        **data,
        "script": body.script,
        "edited": True,
        "edited_at": datetime.utcnow().isoformat(),
    }
    if body.keywords is not None:
        updated["keywords"] = body.keywords
    if body.transition_to_next is not None:
        updated["transition_to_next"] = body.transition_to_next

    # Atomic write
    tmp = script_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(updated, ensure_ascii=False, indent=2))
    tmp.rename(script_path)

    return updated
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| python-pptx text extraction | PyMuPDF span-level PDF parsing | Phase 3 (D-07) | Font metadata enables title auto-detection; works on PDF directly |
| PPTX-only input | PPTX + PDF dual input (D-10) | Phase 3 | PPTX converted to PDF via LibreOffice; PDF parsed by PyMuPDF |
| `import fitz` | `import pymupdf` | PyMuPDF 1.24+ | Package renamed; `import fitz` still works as alias but `pymupdf` is canonical |
| PyMuPDF font flags via numeric constants | Named constants (e.g., `pymupdf.TEXT_FONT_BOLD`) | PyMuPDF 1.24+ | More readable; `TEXT_FONT_BOLD=16, TEXT_FONT_ITALIC=2, TEXT_FONT_SUPERSCRIPT=1` |

**Deprecated/outdated:**
- `import fitz`: Still functional but deprecated in favor of `import pymupdf` since v1.24+
- python-pptx for text extraction in this pipeline: Being replaced by PyMuPDF for richer font metadata

## Open Questions

1. **PyMuPDF coordinate units vs EMU**
   - What we know: PyMuPDF uses points (1/72 inch) for bbox coordinates. Current ShapeRecord uses EMU (1/914400 inch). Conversion factor: 1 pt = 12700 EMU.
   - What's unclear: Whether downstream consumers (VLM prompts, script generation) actually use EMU values, or just the text content.
   - Recommendation: Convert PyMuPDF points to EMU in the parser for schema compatibility. Verify no downstream code depends on precise EMU values.

2. **Celery cpu_queue Worker Configuration**
   - What we know: Current celery_app.py autodiscovers tasks and configures `concurrency=1` for GPU safety. Script tasks should run on `cpu_queue` to not block GPU tasks.
   - What's unclear: Whether a separate Celery worker process is needed for `cpu_queue`, or if the same worker can handle both queues with different concurrency.
   - Recommendation: Run a separate worker: `celery -A lecture_auto.tasks.celery_app worker --queues=cpu_queue --concurrency=2`. Keep existing GPU worker as-is. Add `task_routes` config to `celery_app.py`.

3. **Next.js Portal Integration Details**
   - What we know: Next.js 15.x portal exists on Vercel. Frontend connects directly to GPU server FastAPI for SSE (no proxy).
   - What's unclear: The exact portal repo location, its routing structure, component library (if any), and how to add a new page.
   - Recommendation: The planner should create the Next.js page as a self-contained component. Use minimal dependencies (no component library assumed). The page just needs fetch + EventSource.

4. **`claude -p` Prompt Size Limits**
   - What we know: `call_claude()` passes the entire prompt as a CLI argument. Very long prompts may hit OS argument length limits (typically 128KB-2MB).
   - What's unclear: Whether real slide prompts approach this limit.
   - Recommendation: If prompts exceed ~100KB, switch to stdin piping: `proc = await asyncio.create_subprocess_exec("claude", "-p", stdin=PIPE, ...)` then `proc.communicate(input=prompt.encode())`. Current implementation passes prompt as arg which is fine for typical slide content.

5. **PDF Rendering vs Parsing Consistency**
   - What we know: Phase 1 renderer uses LibreOffice -> pdf2image for PNGs. Phase 3 parser will use PyMuPDF on the same PDF. Both should operate on the same PDF file.
   - What's unclear: Whether the Phase 1 renderer keeps the intermediate PDF or only outputs PNGs.
   - Recommendation: Ensure the LibreOffice PDF is saved to `job_paths.parsed_dir` (or a new `pdf_dir`). Both renderer and parser consume it.

## Sources

### Primary (HIGH confidence)
- [PyMuPDF PyPI](https://pypi.org/project/PyMuPDF/) - Version 1.27.2.2 verified (2026-03-19)
- [PyMuPDF Appendix 1: Text Extraction Details](https://pymupdf.readthedocs.io/en/latest/app1.html) - dict/rawdict structure, span fields
- [PyMuPDF Constants](https://pymupdf.readthedocs.io/en/latest/vars.html) - TEXT_FONT_BOLD=16, TEXT_FONT_ITALIC=2 flags
- [pdfplumber GitHub](https://github.com/jsvine/pdfplumber) - Version 0.11.9, table extraction API
- [pdfplumber PyPI](https://pypi.org/project/pdfplumber/) - Version 0.11.9 verified
- Existing codebase: `vlm_tasks.py`, `progress.py`, `jobs.py`, `script_gen.py`, `parser.py`, `manifest.py` - All read directly

### Secondary (MEDIUM confidence)
- [Celery Task Routing](https://celery.school/celery-task-routing) - Multiple queue configuration patterns
- [Celery Workers Guide](https://docs.celeryq.dev/en/stable/userguide/workers.html) - `--queues` flag documentation
- [Next.js SSE Discussion](https://github.com/vercel/next.js/discussions/48427) - Vercel timeout limitations with SSE
- [Claude Code Headless Docs](https://code.claude.com/docs/en/headless) - `claude -p` subprocess patterns

### Tertiary (LOW confidence)
- PyMuPDF Korean text extraction accuracy - No specific benchmarks found; flagged for pre-implementation testing with real slides (deferred per CONTEXT.md)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - PyMuPDF 1.27.2.2 and pdfplumber 0.11.9 verified on PyPI
- Architecture: HIGH - All backend patterns directly clone existing Phase 2 code; well-understood
- PDF parsing: HIGH - PyMuPDF dict API is well-documented with clear span structure
- Celery integration: HIGH - Existing vlm_tasks.py provides exact template
- Frontend (Next.js): MEDIUM - Portal is external; exact integration patterns need discovery during implementation
- Pitfalls: HIGH - Based on direct code reading and documented API limitations

**Research date:** 2026-03-30
**Valid until:** 2026-04-30 (stable libraries, no fast-moving dependencies)
