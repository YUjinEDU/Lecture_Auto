"""
VLM visual notes module — slide image analysis via the unified LLM client.

Provider/transport lives in :mod:`lecture_auto.llm` (OpenAI by default); this
module only builds the text-grounded prompt, sends image + prompt through the
client, validates the JSON, and computes the grounding (token-overlap) signal.

Exports:
    VlmNote               — Pydantic schema for per-slide visual notes
    build_vlm_prompt      — Build the text-grounded prompt (parsed text + schema)
    generate_visual_notes — Batch entry point: produce VlmNote JSON per slide
    generate_single_note  — Atomic single-slide inference (for resumable tasks)
    compute_token_overlap — Token-level overlap between VLM output and parsed text
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel

from lecture_auto.llm import LLMClient
from lecture_auto.schemas.manifest import SlideRecord

logger = logging.getLogger(__name__)

_TEMPERATURE_FIRST = 0.3
_TEMPERATURE_RETRY = 0.1
_MAX_TOKENS = 1024


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class VlmNote(BaseModel):
    slide_index: int
    visual_summary: str
    key_elements: list[str]
    layout_relations: str
    teaching_points: list[str]
    possible_confusions: list[str]
    needs_review: bool = False
    token_overlap_ratio: float = 1.0


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_vlm_prompt(slide: SlideRecord, rendered_dir: Path | None = None) -> str:
    """Build the text half of the VLM prompt (text-grounded prompting, VLM-02).

    Parsed text from the slide shapes is provided alongside the image (passed
    separately to :meth:`LLMClient.analyze_image`) to curb hallucination.

    Args:
        slide:        SlideRecord with shape/text data.
        rendered_dir: Accepted for backward compatibility; unused (the image is
                      supplied to the LLM client by the caller).

    Returns:
        A prompt string instructing the model to emit the VlmNote JSON schema.
    """
    parsed_texts: list[str] = []
    for shape in slide.shapes:
        if shape.has_text:
            for para in shape.paragraphs:
                if para.full_text.strip():
                    parsed_texts.append(para.full_text.strip())

    parsed_text_block = "\n".join(parsed_texts) if parsed_texts else "(no text on slide)"

    output_schema = (
        "Respond ONLY with valid JSON matching this schema: "
        '{"visual_summary": str, "key_elements": [str], "layout_relations": str, '
        '"teaching_points": [str], "possible_confusions": [str]}'
    )

    return (
        "You are a visual analysis assistant for academic lecture slides. "
        "Analyze the given slide image and produce structured JSON output.\n\n"
        f"Parsed text from this slide:\n{parsed_text_block}\n\n"
        "Now analyze the slide image above.\n\n"
        f"{output_schema}"
    )


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def _parse_vlm_json(text: str, slide_index: int) -> dict:
    """Parse JSON from a VLM response, stripping markdown fences, adding slide_index."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner)
    data = json.loads(text)
    data["slide_index"] = slide_index
    return data


# ---------------------------------------------------------------------------
# Token overlap analysis
# ---------------------------------------------------------------------------

def compute_token_overlap(vlm_text: str, parsed_text: str) -> float:
    """Token-level overlap [0.0, 1.0]: how much of the VLM output is grounded.

    Edge cases:
        - Empty vlm_text    -> 1.0 (nothing to check)
        - Empty parsed_text -> 0.0 (all VLM-generated)
    """
    def tokenize(text: str) -> set[str]:
        return set(re.findall(r"[\w]+", text.lower()))

    vlm_tokens = tokenize(vlm_text)
    parsed_tokens = tokenize(parsed_text)

    if not vlm_tokens:
        return 1.0
    if not parsed_tokens:
        return 0.0
    return len(vlm_tokens & parsed_tokens) / len(vlm_tokens)


def _extract_slide_text(slide: SlideRecord) -> str:
    """Extract all paragraph text from a slide's shapes."""
    texts: list[str] = []
    for shape in slide.shapes:
        if shape.has_text:
            for para in shape.paragraphs:
                if para.full_text.strip():
                    texts.append(para.full_text.strip())
    return " ".join(texts)


# ---------------------------------------------------------------------------
# Inference (single slide = atomic unit for resumable tasks)
# ---------------------------------------------------------------------------

def generate_single_note(
    client: LLMClient,
    slide: SlideRecord,
    rendered_dir: Path,
    vlm_dir: Path,
) -> VlmNote:
    """Generate a VLM note for a single slide and write it to disk.

    Steps:
        1. Build the text-grounded prompt.
        2. Send image + prompt via the LLM client (retry once at lower temperature
           on JSON-parse failure).
        3. Compute token overlap and set the needs_review flag.
        4. Write JSON to vlm_dir/vlm_note_{NNN}.json.

    Args:
        client:       An LLMClient (see lecture_auto.llm.get_llm_client).
        slide:        Single SlideRecord.
        rendered_dir: Directory containing rendered PNGs.
        vlm_dir:      Directory to write the output JSON.

    Returns:
        The validated VlmNote.
    """
    prompt = build_vlm_prompt(slide)
    image_path = rendered_dir / slide.png_path

    response_text = client.analyze_image(
        image_path, prompt, temperature=_TEMPERATURE_FIRST, max_tokens=_MAX_TOKENS
    )

    note: VlmNote | None = None
    try:
        data = _parse_vlm_json(response_text, slide.slide_index)
        note = VlmNote(**data)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "Slide %d: JSON parse failed (%s), retrying at temperature=%.1f",
            slide.slide_number,
            exc,
            _TEMPERATURE_RETRY,
        )
        retry_text = client.analyze_image(
            image_path, prompt, temperature=_TEMPERATURE_RETRY, max_tokens=_MAX_TOKENS
        )
        data = _parse_vlm_json(retry_text, slide.slide_index)
        note = VlmNote(**data)

    # Grounding signal: flag low-overlap notes for human review.
    parsed_text = _extract_slide_text(slide)
    parsed_token_count = len(re.findall(r"[\w]+", parsed_text.lower()))
    vlm_text = " ".join([note.visual_summary, *note.key_elements, *note.teaching_points])
    overlap = compute_token_overlap(vlm_text, parsed_text)

    note = note.model_copy(update={
        "token_overlap_ratio": round(overlap, 3),
        "needs_review": (parsed_token_count > 10 and overlap < 0.30),
    })

    out_path = vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"
    out_path.write_text(
        json.dumps(note.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved VLM note: %s", out_path)
    return note


def generate_visual_notes(
    client: LLMClient,
    slides: list[SlideRecord],
    rendered_dir: Path,
    vlm_dir: Path,
) -> list[VlmNote]:
    """Generate per-slide VLM visual notes and save them to vlm_dir.

    Args:
        client:       An LLMClient (see lecture_auto.llm.get_llm_client).
        slides:       List of SlideRecord objects.
        rendered_dir: Directory containing rendered slide PNGs.
        vlm_dir:      Directory to write vlm_note_*.json outputs.

    Returns:
        Validated VlmNote objects, one per slide, in order.
    """
    notes: list[VlmNote] = []
    for slide in slides:
        logger.info(
            "Processing VLM for slide %d/%d (index=%d)",
            slide.slide_number,
            len(slides),
            slide.slide_index,
        )
        notes.append(generate_single_note(client, slide, rendered_dir, vlm_dir))
    return notes
