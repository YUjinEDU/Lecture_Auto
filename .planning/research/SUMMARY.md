# Research Summary

**Project:** PPT-to-Lecture-Script Automation Pipeline
**Synthesized:** 2026-03-23
**Overall Confidence:** HIGH (STACK/ARCHITECTURE confirmed against current docs; PITFALLS verified against bug trackers and community reports)

---

## Executive Summary

This project is a sequential, GPU-bound automation pipeline that converts Korean academic PPTX files into professor-voiced lecture audio. The recommended approach is a 4-phase build: (1) PPTX parsing + slide rendering infrastructure, (2) VLM analysis + async job backbone, (3) LLM script generation + professor review UI, (4) TTS audio generation + download delivery. Each phase produces a testable deliverable that gates the next phase.

The architecture is deliberately simple: FastAPI + BackgroundTasks on a GPU server, Supabase for job state, local disk for binary artifacts, and Next.js as a thin authenticated proxy. Celery is unnecessary at the single-professor workflow scale. The pipeline calls three subprocess-based AI services (Qwen3-VL via vLLM, Claude via `claude -p`, Qwen3-TTS) rather than loading them in-process, which keeps the API server stable under GPU memory pressure.

The primary risks are correctness risks, not architectural ones: Korean font rendering failures in LibreOffice, VLM hallucination on dense slides, and LLM script incoherence across slide boundaries. All three have documented mitigations that must be built as first-class deliverables — they are not post-MVP polish.

---

## Recommended Stack

| Layer | Technology | Version | Decision Rationale |
|-------|------------|---------|-------------------|
| PPTX parsing | python-pptx | 1.0.2 | Only mature PPTX library; text/notes extraction only |
| Slide rendering | LibreOffice headless + pdf2image + poppler | system 7.6+ / 1.17+ | Only FOSS tool that handles complex PPTX layouts on Linux |
| Image processing | Pillow | 11.x | Required PIL backend; handles VLM pre-processing |
| VLM inference | Qwen3-VL-8B-Instruct via vLLM | transformers >=4.57.0, vLLM >=0.11.0 | 2-5x throughput over naive HuggingFace; fits single 24 GB GPU |
| LLM script generation | Claude via `claude -p` subprocess | current Max Plan | Project constraint; no per-token cost |
| TTS | Qwen3-TTS-12Hz-1.7B-CustomVoice | latest | 3-second voice cloning; 10-language support |
| API server | FastAPI + uvicorn | 0.135.1 | Native async; auto-docs; BackgroundTasks sufficient at this scale |
| Job queue | FastAPI BackgroundTasks + ThreadPoolExecutor | stdlib | No Celery/Redis overhead needed for single-professor workflow |
| Database / auth | Supabase (PostgreSQL 15+) | supabase-py 2.28.3 | Managed; handles job state, user auth, output metadata |
| File storage | Local disk (GPU server) | — | ~1000x faster than S3 for pipeline hot path |
| Frontend | Next.js 15.x (existing) + SSE polling | — | Existing asset; one-way progress events only |
| Schema validation | Pydantic v2 | bundled with FastAPI | Single canonical SlideData model shared across all stages |

**Critical version constraints:**
- `transformers >= 4.57.0` is a hard requirement for Qwen3-VL architecture recognition.
- `vLLM >= 0.11.0` required for Qwen3-VL native support.
- Do NOT use Celery `--concurrency > 1` on GPU workers (OOM/deadlock risk).

---

## Table Stakes Features

Features that must be present at launch. Missing any = product feels broken.

| Feature | Notes |
|---------|-------|
| Per-slide script generation (1:1 mapping) | Core output; must map to slide structure |
| Slide text + visual content extraction | python-pptx for text; PNG + VLM for visual elements |
| Speaker notes ingestion | Professors have existing notes; ignoring them breaks trust |
| Audience + duration metadata input | Drives tone and verbosity in LLM prompt |
| Script preview + inline editing UI | Side-by-side slide thumbnail + editable textarea per slide |
| TTS audio generation from approved script | Hard gate: TTS only after explicit professor approval |
| Job status feedback (per-stage progress) | Async jobs look broken without progress signals |
| Per-slide audio playback | Review audio before accepting the full lecture |
| Download final audio (per-slide or merged zip) | Professor needs deliverable files |
| Error reporting per slide | Identify which slide failed without re-running everything |

---

## Key Differentiators

Features that justify building this tool over commercial alternatives.

| Feature | Value | Complexity |
|---------|-------|------------|
| VLM visual analysis of slides | Captures diagrams, code screenshots, equations text extraction misses | High |
| Professor voice cloning | Lectures sound like the actual professor, not generic TTS | High |
| All-local GPU inference | No data leaves the institution; no per-token API cost for VLM/TTS | Medium |
| Context carry-across slides | Coherent narrative flow across the full deck (not 50 disconnected micro-lectures) | Medium |
| Structured JSON at every stage | Enables debugging, audit, and downstream LMS export | Medium |
| Style parameter (tone/register) | Conversational vs. formal vs. Socratic — one dropdown changes script feel significantly | Low |
| Slide-level re-execution | Re-generate one slide without reprocessing the entire deck | Medium |

**Defer to post-MVP:** pacing/SSML hints, LMS direct push, real-time collaborative editing, multi-language translation.

---

## Architecture Overview

**Five components with hard boundaries:**

```
[Next.js Portal / Vercel]
  |  POST /api/jobs (multipart PPTX)
  v
[FastAPI Gateway / GPU server]
  |  1. Write PPTX to /data/work/{job_id}/
  |  2. INSERT job row to Supabase (status: queued)
  |  3. Enqueue BackgroundTask
  v
[Pipeline Worker / in-process ThreadPoolExecutor]
  Stage 1: python-pptx parse    -> slides.json
  Stage 2: LibreOffice render   -> slide_NNN.png (150-300 DPI)
  Stage 3: Qwen3-VL (vLLM)     -> notes.json
  Stage 4: claude -p subprocess -> script.md
  Stage 5: Professor approval   -> (UI gate, not automated)
  Stage 6: Qwen3-TTS subprocess -> audio_NNN.wav
  |
  | After each stage: UPDATE Supabase (status + progress %)
  v
[Supabase] <-- polled by Next.js every 3s
  v
[Next.js Portal] renders progress, triggers download on complete
```

**Key architectural decisions:**
- Next.js never exposes GPU server directly to browser; all file access via FastAPI signed-download endpoints.
- Status reads bypass FastAPI (browser -> Next.js -> Supabase direct) to reduce GPU server load.
- Audio/script downloads stream from disk; never buffered in memory.
- Next.js passes a shared server-to-server secret to FastAPI; FastAPI has no user auth of its own.
- CORS: FastAPI restricts `allow_origins` to Vercel domain only.

**Canonical file layout:**
```
/data/work/{job_id}/
  input.pptx
  slides.json          # python-pptx parse result
  slide_NNN.png        # rendered at 150-300 DPI
  notes.json           # VLM analysis per slide
  script.md            # Claude-generated scripts
  audio_NNN.wav        # TTS output per slide
```

---

## Critical Pitfalls

Top 5 pitfalls with the highest consequence if missed.

### 1. Korean Font Rendering Failure (LibreOffice headless)
**Risk:** Silent garbled/empty Korean text in PNGs. VLM describes boxes instead of content. Pipeline completes with wrong output.
**Prevention:** Install `fonts-nanum fonts-noto-cjk` before any rendering. Run `fc-list :lang=ko` smoke test in CI. Add post-render OCR check on 3 random slides.
**Phase:** Must fix in Phase 1 before VLM integration.

### 2. python-pptx Silent Content Loss (SmartArt / Charts)
**Risk:** Slides with only diagrams or charts yield empty `text_content`. LLM has no text anchor; script quality degrades for the most explanation-heavy slides.
**Prevention:** Enumerate all shape types; log warnings on `GraphicFrame`. Encode explicit `content_source` field in JSON (`text_frame`, `notes`, `smartart_nodes`, `vlm_only`). Accept charts as VLM-only and flag them.
**Phase:** Phase 1 (PPTX parsing).

### 3. VLM Hallucination on Dense Academic Slides
**Risk:** Qwen3-VL invents equation terms, misreads Korean vocabulary, fabricates chart values. LLM generates scripts with factual errors. Professor trust collapses.
**Prevention:** Always pass python-pptx extracted text to VLM as prompt context. Cross-check token overlap (< 30% triggers professor review flag). Mark VLM-only slides as `needs_review: true`.
**Phase:** Phase 2 (VLM integration). Cross-check is a required deliverable, not optional.

### 4. LLM Script Incoherence Across Slide Boundaries
**Risk:** Each slide regenerated independently reads as 50 disconnected micro-lectures. Professor re-edit workload exceeds writing from scratch.
**Prevention:** Pass `lecture_context` object to each slide prompt: lecture title + previous slide summary + next slide title. Two-pass generation: Pass 1 summaries, Pass 2 scripts with context.
**Phase:** Phase 3. The `lecture_context` schema must be defined in Phase 1 JSON spec.

### 5. No Recovery for Partial Pipeline Failures
**Risk:** A 60-slide deck failing at slide 45 restarts from slide 1, wasting all prior GPU compute.
**Prevention:** Persist per-slide output JSON to disk as each slide completes. On restart, skip slides with existing completed JSON. Add `status: completed|failed|pending` per slide.
**Phase:** Phase 2 (async job infrastructure). This is a requirement, not a nice-to-have.

**Additional medium pitfalls to address:**
- TTS infinite loop on reference audio > 15s (Phase 4): trim to 10-15s, add wall-clock timeout.
- TTS chunking seams in Korean (Phase 4): use `kss` sentence splitter, not period-split; chunks < 150 chars.
- Pydantic schema drift across stages (Phase 1): single canonical `SlideData` model with strict validation at every stage boundary.

---

## Build Order Recommendation

```
Phase 1: Foundation + Parsing Infrastructure
  - Supabase schema (jobs table + per-slide state, RLS policies)
  - FastAPI skeleton (health, CORS, server-to-server auth middleware)
  - /data/work/ directory layout + file utilities
  - python-pptx parser with full shape-type enumeration + content_source field
  - LibreOffice headless renderer at 150-300 DPI with Korean font validation
  - Korean font smoke test + post-render entropy check
  - Single canonical SlideData Pydantic model (shared by all stages)
  - Speaker notes preprocessor (filter meta-notes)
  Delivers: Validated slide JSON + PNG artifacts ready for VLM

Phase 2: Job Lifecycle + VLM Integration
  - POST /jobs endpoint + job state machine in Supabase
  - FastAPI BackgroundTasks + ThreadPoolExecutor (concurrency=1 per GPU)
  - Per-slide checkpoint/restart logic (idempotent stage execution)
  - Qwen3-VL via vLLM subprocess wrapper with text-grounded prompting
  - VLM cross-check (token overlap validation, needs_review flagging)
  Delivers: Resumable async jobs producing per-slide VLM notes JSON

Phase 3: Script Generation + Professor Review UI
  - lecture_context object (title + prev summary + next title)
  - Two-pass Claude script generation (summaries then full scripts)
  - Edit-safe schema: professor_edit field never overwritten by pipeline
  - Token budget estimator + per-deck token logging
  - Professor review UI: slide thumbnail + script textarea + approval gate
  - Inline editing with auto-save draft
  Delivers: Professor-approved scripts ready for TTS

Phase 4: TTS + Download Delivery
  - Voice clone enrollment workflow (10-15s reference audio, trimmed)
  - Qwen3-TTS subprocess wrapper with wall-clock timeout
  - Korean sentence splitter (kss) for TTS chunking at < 150 chars
  - Per-slide WAV output + merged audio assembly
  - Streaming download endpoint (FastAPI -> disk, no memory buffering)
  - Next.js download UI + per-slide audio playback
  Delivers: Complete end-to-end pipeline with downloadable lecture audio
```

**Research flags for planning:**
- Phase 1 (LibreOffice rendering): needs verification on target server's actual PPTX samples before committing to LibreOffice-only path. Complex gradient/transparency slides may need `unoconv` fallback.
- Phase 2 (vLLM deployment): vLLM-Omni for Qwen3-TTS is less documented than vLLM core — validate deployment pattern against QwenLM GitHub before Phase 4 begins.
- Phase 3 (Claude CLI): `claude -p` subprocess is a project constraint, not a documented API. Validate stdout streaming behavior and Max Plan token limits before designing the full batch generation flow.

---

## Open Questions

| Question | Impact | When to Resolve |
|----------|--------|----------------|
| Does the GPU server have a second GPU for concurrent VLM + TTS? If not, stages must be strictly sequential (VLM done before TTS loaded). | Architecture (memory management) | Before Phase 2 |
| What is the expected average slide count per deck? (Impacts per-slide checkpoint design and token budget estimates.) | Phase 2 + 3 design | Before Phase 2 |
| Will professors provide voice clone samples upfront (enrollment session) or per-job? | Phase 4 UX + enrollment flow | Before Phase 3 UI design |
| Is the Next.js portal already deployed with Supabase Auth? Which auth provider (email/password, SSO, etc.)? | Phase 1 Supabase schema must match existing auth.users | Immediately (Phase 1 blocker) |
| Max Plan: what is the monthly token ceiling and reset cadence? | Phase 3 token budget design | Before Phase 3 |
| Are slides expected to be Korean-only, mixed Korean/English, or English-only? | Korean-specific pitfall mitigations may be partially out of scope | Before Phase 1 |

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack (versions + compatibility) | HIGH | All versions verified against current PyPI/HuggingFace/official docs |
| Architecture (component design) | HIGH | Pattern is well-established; FastAPI BackgroundTasks is documented at this scale |
| Features (table stakes + differentiators) | HIGH | Grounded in academic pipeline research + commercial benchmarks |
| Pitfalls (C1-C4) | HIGH | Verified against bug trackers, research papers, and QwenLM GitHub issues |
| Pitfalls (M1-M5) | MEDIUM | Documented but some severity estimates are heuristic |
| LibreOffice rendering fidelity | MEDIUM | Varies by PPTX complexity; must be validated against real lab slides |
| vLLM-Omni for TTS deployment | MEDIUM | Less documentation than vLLM core; offline inference confirmed but details sparse |
| Claude CLI (`claude -p`) stability | MEDIUM | Functional but subprocess stdout streaming is not a documented API contract |
