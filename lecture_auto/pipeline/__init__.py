"""Pipeline package — re-exports all stage modules for easy top-level import.

Usage:
    from lecture_auto.pipeline import parse_pptx, render_slides
    from lecture_auto.pipeline import generate_visual_notes
    from lecture_auto.pipeline import generate_scripts, load_tts, synthesize_audio
    from lecture_auto.pipeline import assemble_video

GPU-dependent modules (vlm, tts, video) use lazy imports so the package
can be loaded in environments without vllm / transformers installed.
"""

from .parser_pptx import parse_pptx
from .parser_pdf import parse_pdf, parse_input, extract_tables_fallback
from .renderer import render_slides

# GPU-dependent modules: import lazily to avoid hard-fail on CPU-only envs
try:
    from .vlm import generate_visual_notes, VlmNote
except ImportError:  # pragma: no cover
    generate_visual_notes = VlmNote = None  # type: ignore[assignment,misc]

try:
    from .script_gen import generate_scripts, SlideScript
except ImportError:  # pragma: no cover
    generate_scripts = SlideScript = None  # type: ignore[assignment,misc]

try:
    from .tts import load_tts, synthesize_audio
except ImportError:  # pragma: no cover
    load_tts = synthesize_audio = None  # type: ignore[assignment,misc]

try:
    from .video import assemble_video, create_slide_clip, concat_clips
except ImportError:  # pragma: no cover
    assemble_video = create_slide_clip = concat_clips = None  # type: ignore[assignment,misc]

__all__ = [
    "parse_pptx",
    "parse_pdf",
    "parse_input",
    "extract_tables_fallback",
    "render_slides",
    "generate_visual_notes",
    "VlmNote",
    "generate_scripts",
    "SlideScript",
    "load_tts",
    "synthesize_audio",
    "assemble_video",
    "create_slide_clip",
    "concat_clips",
]
