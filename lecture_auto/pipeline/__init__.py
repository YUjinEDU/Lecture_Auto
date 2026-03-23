"""Pipeline package — re-exports all stage modules for easy top-level import.

Usage:
    from lecture_auto.pipeline import parse_pptx, render_slides
    from lecture_auto.pipeline import load_vlm, generate_visual_notes
    from lecture_auto.pipeline import generate_scripts, load_tts, synthesize_audio
    from lecture_auto.pipeline import assemble_video
"""

from .parser import parse_pptx
from .renderer import render_slides
from .vlm import load_vlm, generate_visual_notes, VlmNote
from .script_gen import generate_scripts, SlideScript, call_claude
from .tts import load_tts, synthesize_audio
from .video import assemble_video, create_slide_clip, concat_clips

__all__ = [
    "parse_pptx",
    "render_slides",
    "load_vlm",
    "generate_visual_notes",
    "VlmNote",
    "generate_scripts",
    "SlideScript",
    "call_claude",
    "load_tts",
    "synthesize_audio",
    "assemble_video",
    "create_slide_clip",
    "concat_clips",
]
