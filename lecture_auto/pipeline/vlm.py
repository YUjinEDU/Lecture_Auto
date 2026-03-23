"""
VLM visual notes module — Qwen3-VL via vLLM offline inference.

Exports:
    VlmNote           — Pydantic schema for per-slide visual notes
    load_vlm          — Load Qwen3-VL model via vLLM
    build_vlm_prompt  — Build multimodal (image + parsed text) prompt dict
    generate_visual_notes — Main entry point: produce VlmNote JSON per slide
"""
from __future__ import annotations

import json
import logging
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
