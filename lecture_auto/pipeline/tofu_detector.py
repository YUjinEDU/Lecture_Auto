"""Korean font issue detection for rendered slide PNGs.

Two detection strategies (per D-12):
1. Parse LibreOffice stderr for font substitution warnings (primary, MEDIUM confidence)
2. Pixel-level tofu heuristic on rendered PNGs (secondary, LOW confidence)

Per D-13: All results are warnings only -- pipeline never stops for font issues.
"""
from pathlib import Path

import numpy as np
from PIL import Image


def check_font_substitution(soffice_stderr: str) -> list[str]:
    """Parse soffice stderr for font substitution warnings.

    Returns list of warning strings. Empty list = no font issues detected.
    """
    warnings = []
    for line in soffice_stderr.splitlines():
        lower = line.lower()
        if "substitut" in lower or (
            "font" in lower
            and ("not found" in lower or "missing" in lower or "fallback" in lower)
        ):
            warnings.append(line.strip())
    return warnings


def has_tofu_regions(img_path: Path, threshold: float = 0.95) -> bool:
    """Heuristic: detect if a slide PNG likely has tofu (broken Korean characters).

    Tofu characters render as uniform white/light-gray boxes.
    A slide with >threshold proportion of near-white pixels (>240 luminance)
    on a non-blank slide suggests rendering failure.

    Args:
        img_path: Path to PNG file
        threshold: Proportion of near-white pixels to trigger (default 0.95)

    Returns:
        True if slide appears to have tofu rendering issues.
    """
    img = Image.open(img_path).convert("L")  # grayscale
    arr = np.array(img)
    white_ratio = float((arr > 240).sum()) / arr.size
    return white_ratio > threshold


def detect_font_issues(
    soffice_stderr: str,
    png_paths: list[Path],
    tofu_threshold: float = 0.95,
) -> list[str]:
    """Combine stderr parsing and pixel analysis into a single warning list.

    Args:
        soffice_stderr: Raw stderr output from soffice subprocess
        png_paths: List of rendered PNG paths to check
        tofu_threshold: Pixel threshold for tofu detection

    Returns:
        List of warning strings (empty = no issues detected)
    """
    warnings = check_font_substitution(soffice_stderr)
    for png_path in png_paths:
        if png_path.exists() and has_tofu_regions(png_path, tofu_threshold):
            warnings.append(
                f"Possible tofu detected in {png_path.name} (high white-pixel ratio)"
            )
    return warnings
