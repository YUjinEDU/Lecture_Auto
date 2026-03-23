"""Slide rendering pipeline: PPTX -> PDF (LibreOffice) -> PNG (pdf2image).

Key safety measures:
- Per-job UserInstallation isolation prevents LibreOffice lock file races
- 120-second subprocess timeout prevents hung soffice processes
- Temp directory cleanup in finally block
"""
import logging
import os
import shutil
import subprocess
from pathlib import Path

from pdf2image import convert_from_path

from lecture_auto.pipeline.tofu_detector import detect_font_issues

logger = logging.getLogger(__name__)


def pptx_to_pdf(
    pptx_path: Path,
    output_dir: Path,
    job_id: str,
    timeout: int = 120,
) -> tuple[Path, str]:
    """Convert PPTX to PDF using LibreOffice headless.

    Args:
        pptx_path: Path to input PPTX file
        output_dir: Directory for PDF output
        job_id: Used for isolated UserInstallation directory
        timeout: Subprocess timeout in seconds (default 120)

    Returns:
        Tuple of (pdf_path, soffice_stderr)

    Raises:
        RuntimeError: If soffice exits with non-zero code
        FileNotFoundError: If expected PDF is not created
        subprocess.TimeoutExpired: If conversion exceeds timeout
    """
    soffice_bin = os.environ.get("SOFFICE_BIN", "soffice")
    user_install = Path(f"/tmp/soffice-{job_id}")
    user_install.mkdir(exist_ok=True)

    try:
        result = subprocess.run(
            [
                soffice_bin,
                "--headless",
                "--norestore",
                "--nofirststartwizard",
                f"--env:UserInstallation=file://{user_install}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_dir),
                str(pptx_path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"soffice failed (exit {result.returncode}): {result.stderr}"
            )
    finally:
        shutil.rmtree(user_install, ignore_errors=True)

    pdf_name = pptx_path.stem + ".pdf"
    pdf_path = output_dir / pdf_name
    if not pdf_path.exists():
        raise FileNotFoundError(f"Expected PDF not found: {pdf_path}")

    return pdf_path, result.stderr


def pdf_to_pngs(
    pdf_path: Path,
    output_dir: Path,
    dpi: int | None = None,
) -> list[Path]:
    """Convert PDF to numbered PNG slides using pdf2image.

    Args:
        pdf_path: Path to PDF file
        output_dir: Directory for PNG output
        dpi: Resolution (default from RENDER_DPI env var or 150)

    Returns:
        List of PNG paths in slide order: [slide_001.png, slide_002.png, ...]
    """
    if dpi is None:
        dpi = int(os.environ.get("RENDER_DPI", "150"))

    images = convert_from_path(str(pdf_path), dpi=dpi)
    paths = []
    for idx, img in enumerate(images, start=1):
        out = output_dir / f"slide_{idx:03d}.png"
        img.save(str(out), "PNG")
        paths.append(out)
    return paths


def render_slides(
    pptx_path: Path,
    rendered_dir: Path,
    job_id: str,
    dpi: int | None = None,
    timeout: int = 120,
) -> tuple[list[Path], list[str]]:
    """Full rendering pipeline: PPTX -> PDF -> PNGs + font issue detection.

    Args:
        pptx_path: Path to input PPTX file
        rendered_dir: Directory for PNG output
        job_id: Job identifier for process isolation
        dpi: PNG resolution (default from env or 150)
        timeout: soffice timeout in seconds

    Returns:
        Tuple of (list of PNG paths, list of font warning strings)
    """
    rendered_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: PPTX -> PDF
    pdf_path, soffice_stderr = pptx_to_pdf(pptx_path, rendered_dir, job_id, timeout)
    logger.info("PDF created: %s", pdf_path)

    # Step 2: PDF -> PNGs
    png_paths = pdf_to_pngs(pdf_path, rendered_dir, dpi)
    logger.info("Rendered %d slides to PNG", len(png_paths))

    # Step 3: Font issue detection (per D-12, D-13: warn only, don't stop)
    font_warnings = detect_font_issues(soffice_stderr, png_paths)
    if font_warnings:
        for w in font_warnings:
            logger.warning("Font issue: %s", w)

    # Clean up intermediate PDF
    pdf_path.unlink(missing_ok=True)

    return png_paths, font_warnings
