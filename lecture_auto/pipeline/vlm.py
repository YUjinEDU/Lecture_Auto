"""
VLM visual notes module — Qwen3-VL via vLLM offline inference.

Exports:
    VlmNote               — Pydantic schema for per-slide visual notes
    load_vlm              — Load Qwen3-VL model via vLLM
    build_vlm_prompt      — Build multimodal (image + parsed text) prompt dict
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
from vllm import LLM, SamplingParams

from lecture_auto.schemas.manifest import SlideRecord

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"
_DEFAULT_MAX_MODEL_LEN = 4096
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
# Model loading
# ---------------------------------------------------------------------------

def load_vlm(model_path: str = _DEFAULT_MODEL) -> LLM:
    """Load Qwen3-VL via vLLM offline inference.

    Args:
        model_path: HuggingFace model ID or local path.
                    Defaults to "Qwen/Qwen3-VL-8B-Instruct".

    Returns:
        Loaded vLLM LLM instance.
    """
    logger.info("Loading VLM model: %s", model_path)
    llm = LLM(
        model=model_path,
        dtype="auto",
        max_model_len=_DEFAULT_MAX_MODEL_LEN,
        trust_remote_code=True,
    )
    logger.info("VLM model loaded successfully")
    return llm


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def build_vlm_prompt(slide: SlideRecord, rendered_dir: Path) -> dict:
    """Build a multimodal vLLM prompt for one slide.

    Implements text-grounded prompting (VLM-02): parsed text from slide shapes
    is provided alongside the image to prevent hallucination.

    Args:
        slide:        SlideRecord with shape/text data.
        rendered_dir: Directory containing rendered PNG files.

    Returns:
        vLLM messages list suitable for llm.generate().
    """
    image_path = rendered_dir / slide.png_path

    # Collect all paragraph text from shapes that have text
    parsed_texts: list[str] = []
    for shape in slide.shapes:
        if shape.has_text:
            for para in shape.paragraphs:
                if para.full_text.strip():
                    parsed_texts.append(para.full_text.strip())

    parsed_text_block = "\n".join(parsed_texts) if parsed_texts else "(no text on slide)"

    system_content = (
        "You are a visual analysis assistant for academic lecture slides. "
        "Analyze the given slide image and produce structured JSON output."
    )

    output_schema = (
        "Respond ONLY with valid JSON matching this schema: "
        '{"visual_summary": str, "key_elements": [str], "layout_relations": str, '
        '"teaching_points": [str], "possible_confusions": [str]}'
    )

    user_text = (
        f"Parsed text from this slide:\n{parsed_text_block}\n\n"
        f"Now analyze the slide image above.\n\n"
        f"{output_schema}"
    )

    # vLLM multimodal messages format for Qwen3-VL
    messages = [
        {"role": "system", "content": system_content},
        {
            "role": "user",
            "content": [
                {"type": "image", "image": str(image_path)},
                {"type": "text", "text": user_text},
            ],
        },
    ]

    return messages


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _parse_vlm_json(text: str, slide_index: int) -> dict:
    """Parse JSON from VLM response text, adding slide_index."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first (```json or ```) and last (```) lines
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner)
    data = json.loads(text)
    data["slide_index"] = slide_index
    return data


# ---------------------------------------------------------------------------
# Token overlap analysis
# ---------------------------------------------------------------------------

def compute_token_overlap(vlm_text: str, parsed_text: str) -> float:
    """Compute token-level overlap between VLM output and parsed slide text.

    Returns a ratio [0.0, 1.0] indicating how much of the VLM output
    can be grounded in the original parsed text.

    Edge cases:
        - Empty vlm_text  -> 1.0 (nothing to check)
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
# Single-slide inference (atomic unit for resumable tasks)
# ---------------------------------------------------------------------------

def generate_single_note(
    llm: LLM,
    slide: SlideRecord,
    rendered_dir: Path,
    vlm_dir: Path,
) -> VlmNote:
    """Generate a VLM note for a single slide and write to disk.

    Steps:
        1. Build multimodal prompt.
        2. Run inference (temperature=0.3, retry at 0.1 on failure).
        3. Compute token overlap and set needs_review flag.
        4. Write JSON to vlm_dir/vlm_note_{NNN}.json.

    Args:
        llm:          Loaded vLLM LLM instance.
        slide:        Single SlideRecord.
        rendered_dir: Directory containing rendered PNGs.
        vlm_dir:      Directory to write output JSON.

    Returns:
        Validated VlmNote instance.
    """
    prompt = build_vlm_prompt(slide, rendered_dir)

    # First attempt
    sampling_params = SamplingParams(temperature=_TEMPERATURE_FIRST, max_tokens=_MAX_TOKENS)
    results = llm.generate(prompt, sampling_params)
    response_text = results[0].outputs[0].text

    note: VlmNote | None = None
    try:
        data = _parse_vlm_json(response_text, slide.slide_index)
        note = VlmNote(**data)
    except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "Slide %d: JSON parse failed (%s), retrying with temperature=%.1f",
            slide.slide_number,
            exc,
            _TEMPERATURE_RETRY,
        )
        retry_params = SamplingParams(temperature=_TEMPERATURE_RETRY, max_tokens=_MAX_TOKENS)
        retry_results = llm.generate(prompt, retry_params)
        retry_text = retry_results[0].outputs[0].text
        data = _parse_vlm_json(retry_text, slide.slide_index)
        note = VlmNote(**data)

    # Compute token overlap for needs_review flag
    parsed_text = _extract_slide_text(slide)
    parsed_token_count = len(re.findall(r"[\w]+", parsed_text.lower()))

    vlm_text_parts = [note.visual_summary] + note.key_elements + note.teaching_points
    vlm_text = " ".join(vlm_text_parts)
    overlap = compute_token_overlap(vlm_text, parsed_text)

    note = note.model_copy(update={
        "token_overlap_ratio": round(overlap, 3),
        "needs_review": (parsed_token_count > 10 and overlap < 0.30),
    })

    # Write JSON to disk
    out_path = vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"
    out_path.write_text(
        json.dumps(note.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved VLM note: %s", out_path)

    return note


def generate_visual_notes(
    llm: LLM,
    slides: list[SlideRecord],
    rendered_dir: Path,
    vlm_dir: Path,
) -> list[VlmNote]:
    """Generate per-slide VLM visual notes and save to vlm_dir.

    For each slide:
      1. Builds multimodal prompt (image + parsed text).
      2. Runs vLLM inference with SamplingParams(temperature=0.3, max_tokens=1024).
      3. Parses and validates JSON → VlmNote.
      4. On JSON parse failure, retries once with temperature=0.1.
      5. Saves to vlm_dir/vlm_note_{slide_number:03d}.json.

    Args:
        llm:          Loaded vLLM LLM instance (from load_vlm).
        slides:       List of SlideRecord objects.
        rendered_dir: Directory containing rendered slide PNGs.
        vlm_dir:      Directory to write vlm_note_*.json outputs.

    Returns:
        List of validated VlmNote objects (one per slide, in order).
    """
    notes: list[VlmNote] = []

    for slide in slides:
        logger.info(
            "Processing VLM for slide %d/%d (index=%d)",
            slide.slide_number,
            len(slides),
            slide.slide_index,
        )

        prompt = build_vlm_prompt(slide, rendered_dir)

        # First attempt
        sampling_params = SamplingParams(temperature=_TEMPERATURE_FIRST, max_tokens=_MAX_TOKENS)
        results = llm.generate(prompt, sampling_params)
        response_text = results[0].outputs[0].text

        note: VlmNote | None = None
        try:
            data = _parse_vlm_json(response_text, slide.slide_index)
            note = VlmNote(**data)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "Slide %d: JSON parse failed (%s), retrying with temperature=%.1f",
                slide.slide_number,
                exc,
                _TEMPERATURE_RETRY,
            )
            # Retry with lower temperature
            retry_params = SamplingParams(temperature=_TEMPERATURE_RETRY, max_tokens=_MAX_TOKENS)
            retry_results = llm.generate(prompt, retry_params)
            retry_text = retry_results[0].outputs[0].text
            data = _parse_vlm_json(retry_text, slide.slide_index)
            note = VlmNote(**data)

        # Write JSON to vlm_dir
        out_path = vlm_dir / f"vlm_note_{slide.slide_number:03d}.json"
        out_path.write_text(
            json.dumps(note.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved VLM note: %s", out_path)

        notes.append(note)

    return notes
