# Pitfalls Research

**Domain:** PPT-to-Lecture-Script Automation Pipeline (PPTX parsing + VLM + LLM + TTS)
**Researched:** 2026-03-23
**Confidence:** MEDIUM (mix of official docs, community reports, and verified patterns)

---

## Critical Pitfalls

### Pitfall C1: LibreOffice Headless Korean Font Rendering Failure

**What goes wrong:** LibreOffice in headless/server mode silently substitutes Korean fonts with fallback glyphs or renders empty boxes. The PNG output looks valid but contains garbled or missing Korean text. The VLM then describes placeholder rectangles instead of actual content.

**Why it happens:** Headless LibreOffice on Linux does not automatically load the system's Korean language pack. Without `fonts-nanum`, `fonts-noto-cjk`, or equivalent, font substitution silently occurs. This is a documented LibreOffice bug with CJK fonts in headless environments (confirmed in LibreOffice bug tracker and Korean LibreOffice team's 2024 Raspberry Pi analysis).

**Consequences:** VLM reads garbled or empty text regions. LLM generates scripts about "the diagram on this slide" rather than actual slide content. Error is silent — pipeline completes with bad output.

**Warning signs:**
- PNG thumbnails show square boxes or fallback glyphs where Korean text should appear
- VLM output references "unreadable text" or "illegible characters"
- Test with: `fc-list :lang=ko` on the server — empty means Korean fonts missing

**Prevention:**
1. Install Korean fonts before any rendering: `apt-get install -y fonts-nanum fonts-noto-cjk`
2. Add a post-render font-check: randomly sample 3 slides, OCR with pytesseract (`lang='kor'`), assert character count > threshold
3. Include a smoke-test slide with known Korean text in CI
4. Set `LANG=ko_KR.UTF-8` in the LibreOffice headless invocation environment

**Phase:** Address in Phase 1 (PPTX parsing + rendering infrastructure setup). Do not proceed to VLM integration until rendering is verified correct.

---

### Pitfall C2: python-pptx Silent Content Loss for SmartArt, Charts, and Embedded Objects

**What goes wrong:** python-pptx's `.text_frame` and `.text` accessors silently skip `GraphicFrame` shapes containing SmartArt, charts, and OLE objects. A slide with a process diagram in SmartArt yields empty strings. The pipeline sees "no text" and the VLM must infer everything from the image alone.

**Why it happens:** python-pptx treats `GraphicFrame` shapes as opaque containers. `has_smart_art`, `has_chart`, and `has_table` flags exist but text extraction from these requires manual iteration of sub-nodes. Charts' data labels and legend text are not accessible through standard shape traversal.

**Consequences:** Slide metadata JSON has empty `text_content` for diagram-heavy slides. LLM has no text anchor to work from. Script quality degrades for exactly the slides that need most explanation (process flows, data charts).

**Warning signs:**
- Slides with only SmartArt or charts produce empty `extracted_text` in JSON
- Shape type audit shows `MSO_SHAPE_TYPE.GRAPHIC` types ignored in extraction log
- Statistics: if >20% of slides have zero extracted text, the extractor is likely missing content

**Prevention:**
1. Enumerate all shape types during extraction, log a warning for each `GraphicFrame` encountered
2. For SmartArt: iterate `shape.smart_art` node tree to pull all `text_frame.text` values
3. For charts: fall through to LibreOffice-rendered PNG + VLM description only (accept this limitation explicitly)
4. For tables: use `shape.table.iter_cells()` — tables ARE accessible via python-pptx
5. Include shape-type coverage in per-slide metadata JSON

**Phase:** Address in Phase 1 (PPTX parsing). Encode explicit "content_source" field in JSON: `["text_frame", "notes", "smartart_nodes", "vlm_only"]`.

---

### Pitfall C3: VLM Hallucination on Dense Academic Slides

**What goes wrong:** Qwen3-VL produces confident, plausible-sounding descriptions of slide content that do not match actual content. Common patterns: inventing equation terms, misreading Korean technical vocabulary, fabricating data point values from charts, describing a generic "process diagram" instead of the actual labeled steps.

**Why it happens:** VLMs hallucinate at highest rates on (a) dense text overlaid on visuals, (b) domain-specific terminology, (c) small text in diagrams, and (d) cross-lingual content (Chinese-trained model reading Korean). Hallucination persists even in large models (confirmed by DASH, VADE, and 2025 ICLR research).

**Consequences:** LLM script generation receives false premises. Professor finds factual errors in scripts. Revision workload increases to the point that automation provides no time savings. Trust in the system collapses.

**Warning signs:**
- VLM output contains specific numbers, formulas, or Korean terms that look fluent but cannot be verified against extracted text
- VLM describes shapes/objects not visible in the slide image
- Low overlap between python-pptx extracted text and VLM-described text for the same slide

**Prevention:**
1. Always provide python-pptx extracted text to VLM as context in the prompt: "The slide contains the following extracted text: [text]. Now describe what you see visually."
2. Implement a cross-check: compute token overlap between VLM output and extracted text; flag slides with <30% overlap for professor review
3. Use structured VLM prompts that ask for explicit separation: `visual_elements` vs `text_content` vs `layout_description`
4. For chart slides: ask VLM specifically "What values does this chart show? If you cannot read the values clearly, say so."
5. Mark VLM-only slides (no python-pptx text) with a `needs_review: true` flag in JSON

**Phase:** Address in Phase 2 (VLM integration). Validation cross-check is a Phase 2 deliverable, not optional.

---

### Pitfall C4: LLM Script Loses Coherence Across Slide Boundary

**What goes wrong:** Each slide's script is generated independently. The result reads as 50 disconnected micro-lectures instead of one continuous lecture. The professor cannot use it as-is; they must rewrite transitions manually, eliminating most of the value.

**Why it happens:** Slide-level re-execution (a design goal) conflicts with cross-slide narrative coherence. When a slide is regenerated in isolation, the LLM has no knowledge of what was just said or what comes next.

**Consequences:** Poor professor UX. High re-edit rate. The "professor reviews/edits scripts" step takes longer than writing scripts from scratch.

**Warning signs:**
- Generated scripts start each slide with "In this slide, we will discuss..." regardless of context
- No mention of previous slide's topic in transitions
- Slide N+1 re-introduces concepts already established in Slide N

**Prevention:**
1. Pass a `lecture_context` object to each slide prompt containing: (a) lecture title, (b) previous slide's summary sentence, (c) next slide's title
2. For full-deck generation, use a two-pass approach: Pass 1 generates all summaries, Pass 2 generates scripts using summaries as context
3. For slide-level re-execution, require the user to also provide prev/next context (store in JSON alongside script)
4. Include a "transition sentence" field in the script JSON that is explicitly generated as a connector

**Phase:** Address in Phase 3 (LLM script generation). The `lecture_context` schema must be defined in Phase 1 JSON spec.

---

## Medium Pitfalls

### Pitfall M1: TTS Infinite Loop on Long Reference Audio

**What goes wrong:** Qwen3-TTS voice cloning hangs when the reference audio clip is too long. The autoregressive model fails to emit an end-of-sequence token and generates audio indefinitely.

**Why it happens:** Documented issue in Qwen3-TTS GitHub issues. Reference audio beyond ~15 seconds destabilizes the EOS token prediction.

**Warning signs:** TTS job does not complete within expected time; GPU memory climbs monotonically.

**Prevention:**
1. Trim reference audio for voice cloning to 10-15 seconds of clean speech
2. Implement a TTS job timeout (wall-clock, not just token count): kill and requeue after 3x expected duration
3. Log GPU memory trend during TTS; alert if memory grows >10% over 30 seconds

**Phase:** Address in Phase 4 (TTS integration).

---

### Pitfall M2: TTS Chunking Creates Audible Seams in Korean

**What goes wrong:** Long scripts must be chunked before TTS. Chunk boundaries that fall mid-sentence produce audio with unnatural pauses, pitch resets, or prosody breaks at join points. Korean sentence structure (SOV, post-positional particles) makes naive period-split chunking unreliable.

**Why it happens:** Korean sentences frequently end with verb endings that are not followed by periods in academic writing. Splitting on `'.'` alone misses many sentence boundaries and splits others mid-clause.

**Warning signs:**
- Audible click or silence gap at chunk join points
- Sentences split at `'이고', '하며', '으로써'` clause connectors, producing broken prosody

**Prevention:**
1. Use Korean NLP sentence splitter (e.g., `kss` library) rather than period-split
2. Keep chunks under 150 characters (not 300 — Korean characters are more information-dense)
3. Overlap synthesis: generate 0.3s of silence padding at chunk boundaries and cross-fade
4. Add a post-TTS listening check step in the professor review workflow

**Phase:** Address in Phase 4 (TTS). Phase 3 (script generation) should produce scripts with explicit `[PAUSE]` markers to guide chunking.

---

### Pitfall M3: Pydantic JSON Schema Drift Between Pipeline Stages

**What goes wrong:** VLM output JSON schema, LLM input JSON schema, and TTS input JSON schema diverge silently as the project evolves. A field renamed in Phase 2 breaks Phase 3 with a cryptic `KeyError` or Pydantic `ValidationError` that only appears at runtime on the first real deck.

**Why it happens:** Pipeline has 4+ stages each with their own JSON structure. Schema evolution is undisciplined when developers modify prompts.

**Warning signs:**
- Pydantic validation errors appear only on edge-case slides (e.g., slides with no notes)
- Optional fields treated as required in downstream stages
- VLM prompt and LLM prompt use different field names for the same concept

**Prevention:**
1. Define a single `SlideData` Pydantic model as the canonical schema, shared by all stages
2. Use strict Pydantic validation (not `.model_validate` with `strict=False`) at every stage boundary
3. Any schema change requires updating all stage prompt templates in the same commit
4. Include a schema round-trip test: generate dummy `SlideData`, serialize, deserialize, assert equality

**Phase:** Address in Phase 1 (JSON schema design). This is infrastructure, not a feature.

---

### Pitfall M4: LibreOffice PDF Intermediate Step Introduces Rendering Artifacts

**What goes wrong:** The PPTX → PDF → PNG path uses two lossy conversions. Animation artifacts, transparent overlay misalignment, and PDF linearization can all degrade the final PNG used by the VLM.

**Why it happens:** LibreOffice's PDF exporter does not perfectly reproduce all PPTX rendering features, particularly transparent shapes, gradient fills, and embedded video thumbnails.

**Warning signs:**
- PNG shows white boxes where transparent shapes should be
- Text on gradient backgrounds appears with incorrect contrast
- Embedded video frames render as black rectangles

**Prevention:**
1. Use `--impress` export mode with `--headless` and the `draw` filter, not the default impress filter, for sharper PNG output
2. Set export DPI to 150 minimum (300 preferred for small-text slides)
3. After rendering, run a per-slide image entropy check — black or white solid images indicate rendering failure
4. Consider direct PPTX-to-PNG via `unoconv` as a fallback path

**Phase:** Address in Phase 1 (rendering pipeline). Add entropy-based blank-slide detection before any VLM call.

---

### Pitfall M5: Async Job State Machine Has No Recovery for Partial Failures

**What goes wrong:** A 60-slide deck fails at slide 45 during VLM processing (GPU OOM, network timeout, model crash). The job is marked failed. Re-running restarts from slide 1, wasting 44 successful slides' compute.

**Why it happens:** Async job pattern without checkpointing. Each job is treated as atomic.

**Warning signs:**
- Any GPU OOM event causes full job restart
- Re-runs of long decks are indistinguishable from first runs in logs

**Prevention:**
1. Persist per-slide output JSON to disk as each slide completes (not batch at end)
2. On job restart, check for existing per-slide JSON files and skip completed slides
3. Add `status: completed|failed|pending` to each slide's JSON output
4. Slide-level re-execution design goal already implies this — implement it from the start, not as an afterthought

**Phase:** Address in Phase 2 (async job infrastructure). This is a requirement, not a nice-to-have.

---

## Low-Risk Pitfalls

### Pitfall L1: Professor Edit Workflow Has No Diff View

**What goes wrong:** Professor edits a script, then requests a slide re-run. The new generated script overwrites their edits silently. They lose their work.

**Prevention:** Treat professor edits as a separate JSON field (`professor_edit`) never overwritten by pipeline. Show diff between generated and edited versions. Only re-generate `generated_script`; never touch `professor_edit`.

**Phase:** Phase 3 (script review UX).

---

### Pitfall L2: Slide Notes Are Trusted Too Heavily

**What goes wrong:** Lecturer notes often contain outdated content, reminders to themselves ("say this louder"), or incomplete sentences. The LLM incorporates these literally into the lecture script.

**Prevention:** Add a notes preprocessing step that filters out non-content patterns (e.g., lines starting with `*`, `TODO`, `NOTE:`, parenthetical asides). Flag notes that are very short (<20 chars) as likely meta-notes, not content.

**Phase:** Phase 1 (PPTX parsing).

---

### Pitfall L3: VLM Image Resolution Too Low for Fine Text

**What goes wrong:** PNG rendered at 72 DPI (LibreOffice default) produces images where 8pt text in footnotes or table cells is unreadable even to a human. VLM describes "some text at the bottom of the slide" without content.

**Prevention:** Export at 150-300 DPI. Standard 1920x1080 slides at 150 DPI = 1920px wide PNG, which is sufficient for Qwen3-VL's visual encoder.

**Phase:** Phase 1 (rendering pipeline). This is a one-line fix but must be specified from the start.

---

### Pitfall L4: Claude API `claude -p` Token Cost Accumulates Silently

**What goes wrong:** A 50-slide deck with full context (extracted text + VLM analysis + previous summaries) at ~3000 tokens/slide input = 150K tokens per deck. At monthly volume, this can exceed Max Plan limits unexpectedly.

**Prevention:** Log token usage per slide and per deck. Build a token budget estimator before invoking Claude. Cache identical slides (same content hash = same script, no re-generation).

**Phase:** Phase 3 (LLM integration). Add observability from day one.

---

## Phase Mapping

| Phase | Topic | Likely Pitfall | Mitigation |
|-------|-------|---------------|------------|
| Phase 1 | PPTX parsing + rendering | C2 (silent content loss), C1 (Korean fonts), L3 (DPI), L2 (notes noise) | Shape-type audit, font smoke test, DPI setting, notes filter |
| Phase 1 | JSON schema design | M3 (schema drift) | Single canonical Pydantic model, round-trip test |
| Phase 2 | VLM integration | C3 (hallucination), M4 (render artifacts) | Text-grounded prompts, cross-check, entropy check |
| Phase 2 | Async job infrastructure | M5 (no recovery) | Per-slide checkpoint, restart-safe execution |
| Phase 3 | LLM script generation | C4 (coherence), L4 (token cost), L1 (edit overwrite) | lecture_context object, token logging, edit-safe schema |
| Phase 4 | TTS integration | M1 (TTS hang), M2 (seam artifacts) | Reference audio trim, Korean sentence splitter, job timeout |

---

## Sources

- LibreOffice Korean font rendering: [LibreOffice Korean Team 2024 analysis](https://medium.com/libreoffice-korean-team/check-korean-rendering-issues-in-libreoffice-built-on-raspberry-pi-%EB%9D%BC%EC%A6%88%EB%B2%A0%EB%A6%AC%ED%8C%8C%EC%9D%B45%EC%97%90%EC%84%9C-%EB%A6%AC%EB%B8%8C%EB%A0%88%EC%98%A4%ED%94%BC%EC%8A%A4%EC%97%90%EC%84%9C-%ED%95%9C%EA%B5%AD%EC%96%B4-%EA%B8%80%EA%BC%B4%EC%9D%B4%EC%8A%88%ED%99%95%EC%9D%B8-d00b68fa46ca), [LibreOffice Ask: Korean fonts not rendered](https://ask.libreoffice.org/t/korean-fonts-are-not-rendered-during-document-conversion/29178)
- python-pptx SmartArt/Chart gaps: [Extract Text including SmartArt](https://medium.com/@alice.yang_10652/extract-text-from-powerpoint-ppt-or-pptx-with-python-shapes-tables-notes-smartart-and-more-18e1381018e0)
- VLM hallucination research: [DASH benchmark (ICCV 2025)](https://openaccess.thecvf.com/content/ICCV2025/papers/Augustin_DASH_Detection_and_Assessment_of_Systematic_Hallucinations_of_VLMs_ICCV_2025_paper.pdf), [Mitigating Image Captioning Hallucinations (2025)](https://arxiv.org/html/2505.03420)
- LLM long-form coherence: [Hierarchical Expansion for Coherent Long-Form Content](https://opencredo.com/blogs/how-to-use-llms-to-generate-coherent-long-form-content-using-hierarchical-expansion)
- Qwen3-TTS voice cloning issues: [Qwen3-TTS GitHub](https://github.com/QwenLM/Qwen3-TTS), [Voice Cloning Guide 2026](https://ocdevel.com/blog/20260302-qwen-tts-voice-cloning)
- TTS chunking: [Deepgram TTS text chunking](https://developers.deepgram.com/docs/tts-text-chunking), [Qwen3 Audiobook Converter (chunk patterns)](https://github.com/WhiskeyCoder/Qwen3-Audiobook-Converter)
- Async GPU pipelines: [Oracle: Async Queues for GPU Utilization](https://blogs.oracle.com/cloud-infrastructure/why-asynchronous-queues-are-the-savio-gpu-utilization)
