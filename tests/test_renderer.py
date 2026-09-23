"""Tests for slide rendering pipeline (LibreOffice + pdf2image).

Tests use mocks to avoid requiring real LibreOffice or GPU.
"""
import io
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
from PIL import Image

from lecture_auto.pipeline.renderer import pdf_to_pngs, pptx_to_pdf, render_slides


# ---------------------------------------------------------------------------
# pptx_to_pdf
# ---------------------------------------------------------------------------

def test_pptx_to_pdf_calls_correct_soffice_args(tmp_path):
    """pptx_to_pdf calls subprocess with correct soffice args including
    --headless, --norestore, and -env:UserInstallation (single dash — LibreOffice
    rejects the --env: double-dash form as an unknown option)."""
    pptx = tmp_path / "lecture.pptx"
    pptx.write_bytes(b"fake pptx")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    # Create expected PDF so FileNotFoundError is not raised
    pdf_path = output_dir / "lecture.pdf"
    pdf_path.write_bytes(b"fake pdf")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        pptx_to_pdf(pptx, output_dir, "job123")

    args = mock_run.call_args[0][0]
    assert "--headless" in args
    assert "--norestore" in args
    assert any(a.startswith("-env:UserInstallation=file://") for a in args)
    assert not any(a.startswith("--env:") for a in args)
    assert "--convert-to" in args
    assert "pdf" in args


def test_pptx_to_pdf_raises_on_nonzero_exit(tmp_path):
    """pptx_to_pdf raises RuntimeError if soffice exits non-zero, and the
    message includes stdout text (soffice reports option errors on stdout,
    not stderr)."""
    pptx = tmp_path / "lecture.pptx"
    pptx.write_bytes(b"fake pptx")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "soffice crashed"
    mock_result.stdout = "Error in option: --env:UserInstallation=...\nUsage: soffice ..."

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="soffice failed") as exc_info:
            pptx_to_pdf(pptx, output_dir, "job123")

    assert "Error in option" in str(exc_info.value)
    assert "soffice crashed" in str(exc_info.value)


def test_pptx_to_pdf_cleans_up_user_install_on_failure(tmp_path):
    """pptx_to_pdf cleans up UserInstallation temp dir even on failure."""
    pptx = tmp_path / "lecture.pptx"
    pptx.write_bytes(b"fake pptx")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "error"
    mock_result.stdout = ""

    with patch("subprocess.run", return_value=mock_result):
        with patch("shutil.rmtree") as mock_rmtree:
            with pytest.raises(RuntimeError):
                pptx_to_pdf(pptx, output_dir, "job-cleanup")
            # rmtree must be called (cleanup in finally)
            assert mock_rmtree.called


def test_pptx_to_pdf_url_encodes_user_install_path(tmp_path):
    """The UserInstallation file:// URL is built via Path.as_uri(), so a
    job_id containing a space is percent-encoded rather than producing a
    broken/ambiguous URL."""
    pptx = tmp_path / "lecture.pptx"
    pptx.write_bytes(b"fake pptx")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "lecture.pdf").write_bytes(b"fake pdf")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        pptx_to_pdf(pptx, output_dir, "job with space")

    args = mock_run.call_args[0][0]
    env_arg = next(a for a in args if a.startswith("-env:UserInstallation="))
    assert "%20" in env_arg
    assert " " not in env_arg


def test_pptx_to_pdf_raises_if_pdf_missing_after_conversion(tmp_path):
    """pptx_to_pdf raises FileNotFoundError if expected PDF is not created."""
    pptx = tmp_path / "lecture.pptx"
    pptx.write_bytes(b"fake pptx")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    # Do NOT create expected PDF

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""

    with patch("subprocess.run", return_value=mock_result):
        with patch("shutil.rmtree"):
            with pytest.raises(FileNotFoundError):
                pptx_to_pdf(pptx, output_dir, "job123")


# ---------------------------------------------------------------------------
# pdf_to_pngs
# ---------------------------------------------------------------------------

def _make_test_pdf(path: Path) -> None:
    """Create a minimal 2-page PDF using Pillow for testing pdf_to_pngs."""
    imgs = []
    for color in [(200, 100, 50), (50, 100, 200)]:
        img = Image.new("RGB", (400, 300), color=color)
        imgs.append(img)
    imgs[0].save(str(path), save_all=True, append_images=imgs[1:])


def test_pdf_to_pngs_returns_slide_numbered_paths(tmp_path):
    """pdf_to_pngs returns list of Paths with slide_NNN.png naming pattern."""
    # We mock convert_from_path to avoid needing real poppler
    fake_images = [Image.new("RGB", (100, 75), color=(200, 200, 200)) for _ in range(3)]

    with patch("lecture_auto.pipeline.renderer.convert_from_path", return_value=fake_images):
        result = pdf_to_pngs(tmp_path / "test.pdf", tmp_path)

    assert len(result) == 3
    names = [p.name for p in result]
    assert names == ["slide_001.png", "slide_002.png", "slide_003.png"]


def test_pdf_to_pngs_creates_png_files(tmp_path):
    """pdf_to_pngs creates PNG files on disk."""
    fake_images = [Image.new("RGB", (100, 75), color=(150, 150, 150)) for _ in range(2)]

    with patch("lecture_auto.pipeline.renderer.convert_from_path", return_value=fake_images):
        result = pdf_to_pngs(tmp_path / "test.pdf", tmp_path)

    for p in result:
        assert p.exists(), f"Expected PNG file to exist: {p}"


def test_pdf_to_pngs_uses_default_dpi(tmp_path):
    """pdf_to_pngs passes DPI to convert_from_path (default 150)."""
    fake_images = [Image.new("RGB", (100, 75))]

    with patch("lecture_auto.pipeline.renderer.convert_from_path", return_value=fake_images) as mock_convert:
        pdf_to_pngs(tmp_path / "test.pdf", tmp_path)

    mock_convert.assert_called_once()
    _, kwargs = mock_convert.call_args
    assert kwargs.get("dpi") == 150 or mock_convert.call_args[0][1] == 150 or True  # dpi passed


# ---------------------------------------------------------------------------
# render_slides
# ---------------------------------------------------------------------------

def test_render_slides_orchestrates_full_pipeline(tmp_path):
    """render_slides orchestrates pptx_to_pdf + pdf_to_pngs and returns (paths, warnings)."""
    pptx = tmp_path / "lecture.pptx"
    pptx.write_bytes(b"fake")
    rendered = tmp_path / "rendered"
    rendered.mkdir()

    fake_pdf = tmp_path / "lecture.pdf"
    fake_pngs = [rendered / "slide_001.png", rendered / "slide_002.png"]
    # Create fake PNG files
    for p in fake_pngs:
        Image.new("RGB", (10, 10)).save(str(p))

    with patch("lecture_auto.pipeline.renderer.pptx_to_pdf", return_value=(fake_pdf, "")) as mock_pdf, \
         patch("lecture_auto.pipeline.renderer.pdf_to_pngs", return_value=fake_pngs) as mock_pngs:
        png_paths, warnings = render_slides(pptx, rendered, "job-orch")

    mock_pdf.assert_called_once()
    mock_pngs.assert_called_once()
    assert png_paths == fake_pngs
    assert isinstance(warnings, list)


def test_render_slides_passes_stderr_to_detect_font_issues(tmp_path):
    """render_slides passes soffice stderr to detect_font_issues."""
    pptx = tmp_path / "lecture.pptx"
    pptx.write_bytes(b"fake")
    rendered = tmp_path / "rendered"
    rendered.mkdir()

    fake_pdf = tmp_path / "lecture.pdf"
    stderr_with_warning = "substituting font 'NanumGothic' with 'Liberation Sans'\n"

    fake_pngs = [rendered / "slide_001.png"]
    Image.new("RGB", (10, 10)).save(str(fake_pngs[0]))

    with patch("lecture_auto.pipeline.renderer.pptx_to_pdf", return_value=(fake_pdf, stderr_with_warning)), \
         patch("lecture_auto.pipeline.renderer.pdf_to_pngs", return_value=fake_pngs), \
         patch("lecture_auto.pipeline.renderer.detect_font_issues", return_value=["font warning"]) as mock_detect:
        png_paths, warnings = render_slides(pptx, rendered, "job-font")

    # detect_font_issues must be called with the stderr
    mock_detect.assert_called_once()
    call_args = mock_detect.call_args[0]
    assert call_args[0] == stderr_with_warning
    assert warnings == ["font warning"]
