"""Tests for Korean font issue detection module.

Tests cover:
1. check_font_substitution: clean stderr, substitution warnings, case-insensitive
2. has_tofu_regions: normal image, mostly-white image
3. detect_font_issues: combined detection
"""
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lecture_auto.pipeline.tofu_detector import (
    check_font_substitution,
    detect_font_issues,
    has_tofu_regions,
)


# ---------------------------------------------------------------------------
# check_font_substitution
# ---------------------------------------------------------------------------

def test_check_font_substitution_clean_stderr():
    """Returns empty list when soffice stderr has no font warnings."""
    stderr = "Loading BASIC IDE\nDocument loaded successfully\n"
    result = check_font_substitution(stderr)
    assert result == []


def test_check_font_substitution_detects_substituting_font():
    """Returns warning strings when stderr contains 'substituting font' lines."""
    stderr = (
        "Loading BASIC IDE\n"
        "Substituting font 'NanumGothic' with 'Liberation Sans'\n"
        "Document loaded successfully\n"
    )
    result = check_font_substitution(stderr)
    assert len(result) == 1
    assert "Substituting font" in result[0]


def test_check_font_substitution_case_insensitive():
    """Catches font warning lines case-insensitively."""
    stderr = (
        "SUBSTITUTING FONT 'Malgun Gothic' WITH 'DejaVu Sans'\n"
        "font not found: Batang\n"
        "FONT MISSING: HY신명조\n"
    )
    result = check_font_substitution(stderr)
    assert len(result) == 3


def test_check_font_substitution_multiple_lines():
    """Returns all matching lines when multiple font warnings exist."""
    stderr = (
        "substituting font 'A' with 'B'\n"
        "substituting font 'C' with 'D'\n"
        "Normal log line\n"
        "font fallback used for glyph 0x1234\n"
    )
    result = check_font_substitution(stderr)
    assert len(result) == 3  # 2 substituting + 1 fallback


# ---------------------------------------------------------------------------
# has_tofu_regions
# ---------------------------------------------------------------------------

def test_has_tofu_regions_normal_image_returns_false(tmp_path):
    """Returns False for a colorful image with varied pixel values (no tofu)."""
    # Create 100x100 image with random colorful pixels
    rng = np.random.default_rng(42)
    pixels = rng.integers(0, 200, size=(100, 100), dtype=np.uint8)
    img = Image.fromarray(pixels, mode="L")
    img_path = tmp_path / "normal.png"
    img.save(str(img_path))

    assert has_tofu_regions(img_path) is False


def test_has_tofu_regions_nearly_white_image_returns_true(tmp_path):
    """Returns True for a nearly all-white image (>95% near-white pixels)."""
    # Create 100x100 image with all pixels = 250 (well above 240 threshold)
    pixels = np.full((100, 100), 250, dtype=np.uint8)
    img = Image.fromarray(pixels, mode="L")
    img_path = tmp_path / "white.png"
    img.save(str(img_path))

    assert has_tofu_regions(img_path) is True


# ---------------------------------------------------------------------------
# detect_font_issues
# ---------------------------------------------------------------------------

def test_detect_font_issues_combines_stderr_and_pixel_analysis(tmp_path):
    """Combines stderr warnings and pixel analysis into a single warning list."""
    # Stderr with one font warning
    stderr = "substituting font 'NanumGothic' with 'Liberation Sans'\n"

    # One normal PNG (no tofu) and one white PNG (tofu)
    normal_pixels = np.random.default_rng(0).integers(0, 200, size=(50, 50), dtype=np.uint8)
    normal_img = Image.fromarray(normal_pixels, mode="L")
    normal_path = tmp_path / "slide_001.png"
    normal_img.save(str(normal_path))

    white_pixels = np.full((50, 50), 252, dtype=np.uint8)
    white_img = Image.fromarray(white_pixels, mode="L")
    white_path = tmp_path / "slide_002.png"
    white_img.save(str(white_path))

    result = detect_font_issues(stderr, [normal_path, white_path])

    # Should have: 1 from stderr + 1 from pixel (white slide)
    assert len(result) == 2
    assert any("substituting" in w.lower() for w in result)
    assert any("slide_002.png" in w for w in result)


def test_detect_font_issues_empty_when_no_issues(tmp_path):
    """Returns empty list when no stderr warnings and no tofu PNGs."""
    stderr = "Loading BASIC IDE\n"
    normal_pixels = np.random.default_rng(1).integers(0, 180, size=(50, 50), dtype=np.uint8)
    img = Image.fromarray(normal_pixels, mode="L")
    png_path = tmp_path / "slide_001.png"
    img.save(str(png_path))

    result = detect_font_issues(stderr, [png_path])
    assert result == []


def test_detect_font_issues_skips_nonexistent_paths(tmp_path):
    """Pixel analysis skips PNG paths that do not exist."""
    stderr = ""
    nonexistent = tmp_path / "does_not_exist.png"

    result = detect_font_issues(stderr, [nonexistent])
    assert result == []
