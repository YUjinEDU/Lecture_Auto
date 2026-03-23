# Features Research

**Domain:** PPT-to-Lecture-Script Automation (academic, professor-facing)
**Researched:** 2026-03-23
**Project context:** PPTX + metadata → parse → render PNG → VLM notes → Claude script → TTS (voice-cloned) audio, with professor review portal

---

## Table Stakes

Features users expect. Missing = product feels incomplete or untrustworthy.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Per-slide script generation | Core output — one narration block per slide | Medium | Must map 1:1 to slide structure |
| Slide content extraction (text + layout) | Needed to ground script in actual slide content | Medium | python-pptx for text; PNG render for visual elements |
| Speaker notes ingestion | Professors often have existing notes; ignoring them breaks trust | Low | Merge with VLM notes as context |
| Audience + duration metadata input | Scripts must match level (undergrad vs. grad) and time budget | Low | Simple form fields; drives tone and verbosity prompts |
| Script preview / review UI | Professor must see and approve before TTS; mandatory for adoption | Medium | Side-by-side slide thumbnail + script text |
| Inline script editing | Professors will always want to tweak phrasing | Medium | Plain textarea per slide; auto-save draft |
| TTS audio generation from approved script | End-to-end pipeline completion | High | Voice clone with Qwen3-TTS |
| Job status feedback (submit → processing → done) | Async jobs look broken without progress signals | Medium | Polling or WebSocket; show per-stage progress |
| Per-slide audio playback | Review audio before accepting the full lecture | Low | HTML5 audio player inline |
| Download final audio (per-slide or full merged) | Professors need deliverable files | Low | Zip download or individual files |
| Error reporting per slide | Identify which slide failed without re-running everything | Medium | Stage-level error state in job JSON |

---

## Differentiators

Features that set this product apart. Not universally expected, but high value for the target user.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| VLM visual analysis of slide images | Captures diagrams, code screenshots, equations that text extraction misses — critical for CS lectures | High | Render PNG per slide, pass to VLM; output merged with text notes |
| Professor voice cloning | Lectures sound like the actual professor, not a generic TTS voice | High | Requires voice sample enrollment; Qwen3-TTS fine-tune or prompt |
| Slide-level re-execution | Re-generate only a single slide's script or audio without reprocessing the entire deck | Medium | Job graph with per-slide state; idempotent stage execution |
| Style parameter (tone/register) | "Conversational lecture" vs. "formal narration" vs. "Socratic questioning" changes script feel significantly | Low | Prompt parameter; dropdown in UI |
| All intermediate outputs as structured JSON | Enables debugging, auditing, and downstream tool integration (LMS export, transcript indexing) | Medium | Explicit schema per stage: parse_result, vlm_notes, script, tts_manifest |
| Lecture-aware pacing hints | Script includes natural pause markers, emphasis cues, section transitions — not just raw narration | Medium | Prompt engineering; optional SSML tags for TTS |
| Context carry-across slides | Script generator receives prior slide summaries so narrative flows coherently across the deck | Medium | Sliding context window passed to Claude per slide |
| Batch job for full deck + selective override | Submit entire deck at once; override individual slides without losing the rest | Medium | Requires per-slide job state tracking |

---

## Anti-Features

Things to deliberately NOT build in this system.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Automatic slide re-design / visual editing | Scope creep; professors own their slide decks and don't want AI modifying visuals | Read slides as-is; treat PPTX as immutable input |
| Quiz/assessment generation from slides | Different product category; dilutes focus and adds content-safety complexity | Out of scope; refer to dedicated tools (Quizlet, Coursera AI) |
| Real-time collaborative editing of scripts | Adds significant infrastructure complexity for a single-professor workflow | Async edit-then-approve is sufficient; avoid live collab |
| Full video rendering (avatar + slides) | Doubles scope; video sync is a separate hard problem | Deliver audio only; professor assembles video if needed |
| LMS direct push (Canvas/Moodle integration) | Each LMS has its own auth/API surface; high integration cost for uncertain use | Export downloadable files; professor uploads manually |
| Auto-publish without professor approval | Breaks pedagogical trust; professor must be in the loop before audio goes live | Hard gate: TTS only triggers after explicit script approval |
| Multi-language translation of scripts | NLP translation quality is inconsistent for technical CS content; adds hallucination risk | Single language (professor's native language) per run |
| Real-time streaming TTS during editing | Complexity without value; professor edits before TTS, not during | Generate TTS only on approved, finalized script |

---

## Feature Dependencies

```
PPTX parse (text extraction)
    └── Slide PNG render
            └── VLM visual notes
                    └── Script generation (Claude)
                            ├── Professor review UI
                            │       └── Inline editing
                            │               └── Approval gate
                            │                       └── TTS audio generation
                            │                               ├── Per-slide audio playback
                            │                               └── Download (per-slide / merged)
                            └── Context carry-across slides (requires ordered script outputs)

Speaker notes ingestion → feeds into Script generation (parallel with VLM notes)
Audience/duration metadata → feeds into Script generation prompt
Style parameter → feeds into Script generation prompt
Voice clone model → prerequisite for TTS (enrollment before first job)
Slide-level re-execution → requires per-slide job state in job graph
Error reporting per slide → requires stage-level state tracking in job JSON
```

### Critical Path

The critical path is: PPTX parse → PNG render → VLM → Script → Approval → TTS.
All metadata inputs (audience, duration, style, speaker notes) must be collected before the script generation stage. Voice clone enrollment must happen before any TTS stage executes. Slide-level re-execution is an optimization layered on top of this path, not a prerequisite for MVP.

---

## MVP Recommendation

Prioritize:
1. PPTX parse + PNG render (foundation for everything)
2. VLM visual notes per slide
3. Script generation with metadata parameters (audience, duration, style)
4. Professor review + inline editing UI
5. TTS with professor's voice clone
6. Job status feedback + per-slide audio playback + download

Defer for post-MVP:
- Slide-level re-execution (MVP can re-run the full deck; fine-grained re-execution adds infra complexity)
- Lecture-aware pacing hints and SSML (can start with plain script; add prosody layer later)
- Context carry-across slides (start stateless per slide; add context window when quality is insufficient)

---

## Sources

- [SlideNarrator: AI Slide Narration & Video Maker](https://www.slidenarrator.com/) — commercial benchmark for PPT narration features
- [Transforming Higher Education with AI-Powered Video Lectures (arXiv 2511.20660)](https://arxiv.org/abs/2511.20660) — semi-automated academic lecture pipeline (Gemini + Polly + PowerPoint)
- [Generating Narrated Lecture Videos from Slides with Synchronized Highlights (arXiv 2505.02966)](https://arxiv.org/html/2505.02966v1) — AutoLectures system, slide-level highlight sync
- [Paper2Video: Automatic Video Generation from Scientific Papers](https://arxiv.org/html/2510.05096v2) — VLM-based subtitle and cursor alignment per slide
- [Murf.ai Voice Over Presentations](https://murf.ai/voiceover/presentations) — TTS + voice cloning commercial feature reference
- [The 8 best AI presentation makers in 2026 (Zapier)](https://zapier.com/blog/best-ai-presentation-maker/) — market overview
- [Best AI Presentation Makers (Plus AI blog)](https://plusai.com/blog/best-ai-presentation-makers) — feature comparison across tools
