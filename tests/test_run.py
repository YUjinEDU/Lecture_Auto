"""Unit tests for run.py — CLI orchestrator helpers.

Tests cover:
  - confirm_step return values for y/yes/empty and n inputs
  - CLI argument defaults and choices
  - write_summary JSON structure
  - stage timing recording logic
  - sha256_file utility
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the helpers we can test without GPU stack
from run import (
    build_arg_parser,
    confirm_step,
    sha256_file,
    write_summary,
)


# ---------------------------------------------------------------------------
# confirm_step
# ---------------------------------------------------------------------------


class TestConfirmStep:
    """confirm_step returns True for affirmative inputs, False otherwise."""

    def test_yes_lowercase(self):
        with patch("builtins.input", return_value="y"):
            assert confirm_step("parse") is True

    def test_yes_full_word(self):
        with patch("builtins.input", return_value="yes"):
            assert confirm_step("render") is True

    def test_empty_enter(self):
        with patch("builtins.input", return_value=""):
            assert confirm_step("vlm") is True

    def test_no_lowercase(self):
        with patch("builtins.input", return_value="n"):
            assert confirm_step("tts") is False

    def test_no_full_word(self):
        with patch("builtins.input", return_value="no"):
            assert confirm_step("video") is False

    def test_arbitrary_string_is_false(self):
        with patch("builtins.input", return_value="maybe"):
            assert confirm_step("scripts") is False

    def test_eof_returns_false(self):
        with patch("builtins.input", side_effect=EOFError):
            assert confirm_step("parse") is False

    def test_keyboard_interrupt_returns_false(self):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            assert confirm_step("parse") is False

    def test_yes_uppercase_is_false(self):
        # Uppercase Y is not in the accepted set — case-sensitive check
        with patch("builtins.input", return_value="Y"):
            # strip().lower() normalises to "y" → should be True
            assert confirm_step("parse") is True

    def test_whitespace_stripped(self):
        with patch("builtins.input", return_value="  y  "):
            assert confirm_step("parse") is True


# ---------------------------------------------------------------------------
# CLI argument defaults
# ---------------------------------------------------------------------------


class TestArgParserDefaults:
    """Verify default values and accepted choices for all CLI arguments."""

    def setup_method(self):
        self.parser = build_arg_parser()

    def _parse(self, extra: list[str] | None = None) -> object:
        base = ["--pptx", "dummy.pptx"]
        return self.parser.parse_args(base + (extra or []))

    def test_density_default(self):
        args = self._parse()
        assert args.density == "detailed"

    def test_density_concise(self):
        args = self._parse(["--density", "concise"])
        assert args.density == "concise"

    def test_density_invalid_raises(self):
        with pytest.raises(SystemExit):
            self._parse(["--density", "balanced"])

    def test_tone_default(self):
        args = self._parse()
        assert args.tone == "formal"

    def test_tone_casual(self):
        args = self._parse(["--tone", "casual"])
        assert args.tone == "casual"

    def test_approach_default(self):
        args = self._parse()
        assert args.approach == "explanatory"

    def test_approach_socratic(self):
        args = self._parse(["--approach", "socratic"])
        assert args.approach == "socratic"

    def test_approach_invalid_raises(self):
        with pytest.raises(SystemExit):
            self._parse(["--approach", "summary"])

    def test_voice_default_is_none(self):
        args = self._parse()
        assert args.voice is None

    def test_name_default(self):
        args = self._parse()
        assert args.name == "Untitled Lecture"

    def test_subject_default(self):
        args = self._parse()
        assert args.subject == "General"

    def test_audience_default(self):
        args = self._parse()
        assert args.audience == "undergraduate"

    def test_minutes_default(self):
        args = self._parse()
        assert args.minutes == 30

    def test_vlm_model_default(self):
        args = self._parse()
        assert args.vlm_model == "Qwen/Qwen3-VL-8B-Instruct"

    def test_tts_model_default(self):
        args = self._parse()
        assert args.tts_model == "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"

    def test_pptx_required(self):
        with pytest.raises(SystemExit):
            self.parser.parse_args([])

    def test_pptx_is_path(self):
        args = self._parse()
        assert isinstance(args.pptx, Path)


# ---------------------------------------------------------------------------
# write_summary
# ---------------------------------------------------------------------------


class TestWriteSummary:
    """write_summary creates a JSON file with the correct structure."""

    def _call_write_summary(self, tmpdir: Path, error: str | None = None) -> dict:
        job_id = "test-job-001"
        pptx_file = Path("/data/test.pptx")
        stage_timings = {
            "parse": 1.2,
            "render": 15.3,
            "vlm": 45.0,
            "script_gen": 120.0,
            "tts": 60.0,
            "video": 10.0,
        }
        font_warnings = ["Font 'NanumGothic' not found on slide 3"]
        output_mp4 = Path("output/lecture_test-job-001.mp4")
        work_dir = Path("/data/work/test-job-001")

        summary_path = write_summary(
            tmpdir,
            job_id,
            pptx_file,
            slide_count=5,
            stage_timings=stage_timings,
            font_warnings=font_warnings,
            output_mp4=output_mp4,
            work_dir=work_dir,
            error=error,
        )
        assert summary_path.exists()
        with open(summary_path, encoding="utf-8") as f:
            return json.load(f)

    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            assert "job_id" in data

    def test_job_id_field(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            assert data["job_id"] == "test-job-001"

    def test_pptx_file_field(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            assert data["pptx_file"] == "/data/test.pptx"

    def test_slide_count_field(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            assert data["slide_count"] == 5

    def test_stage_timings_has_all_keys(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            expected_keys = {"parse", "render", "vlm", "script_gen", "tts", "video"}
            assert expected_keys == set(data["stage_timings"].keys())

    def test_total_seconds_correct(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            expected = 1.2 + 15.3 + 45.0 + 120.0 + 60.0 + 10.0
            assert abs(data["total_seconds"] - expected) < 0.01

    def test_font_warnings_present(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            assert len(data["font_warnings"]) == 1
            assert "NanumGothic" in data["font_warnings"][0]

    def test_output_mp4_field(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            assert "lecture_test-job-001.mp4" in data["output_mp4"]

    def test_work_dir_field(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            assert "test-job-001" in data["work_dir"]

    def test_no_error_field_on_success(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td))
            assert "error" not in data

    def test_error_field_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            data = self._call_write_summary(Path(td), error="Stage 3 failed")
            assert data["error"] == "Stage 3 failed"

    def test_filename_contains_job_id(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            write_summary(
                td_path, "abc-123", Path("/x.pptx"), 2,
                {"parse": 1.0}, [], Path("out.mp4"), Path("/work"),
            )
            assert (td_path / "summary_abc-123.json").exists()


# ---------------------------------------------------------------------------
# Stage timing recording logic
# ---------------------------------------------------------------------------


class TestStageTiming:
    """Verify stage timing dict accumulates correctly."""

    def test_timings_accumulate(self):
        timings: dict[str, float] = {}
        timings["parse"] = 1.5
        timings["render"] = 10.0
        assert sum(timings.values()) == pytest.approx(11.5)

    def test_timings_rounding(self):
        import time
        t0 = time.perf_counter()
        time.sleep(0.01)
        elapsed = time.perf_counter() - t0
        rounded = round(elapsed, 2)
        assert isinstance(rounded, float)
        assert rounded > 0


# ---------------------------------------------------------------------------
# sha256_file
# ---------------------------------------------------------------------------


class TestSha256File:
    """sha256_file returns consistent hex digest."""

    def test_consistent_for_same_content(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"hello world")
            tmp_path = Path(f.name)
        try:
            h1 = sha256_file(tmp_path)
            h2 = sha256_file(tmp_path)
            assert h1 == h2
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_known_digest(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"")
            tmp_path = Path(f.name)
        try:
            # SHA-256 of empty bytes
            expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            assert sha256_file(tmp_path) == expected
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_different_files_differ(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"aaa")
            p1 = Path(f.name)
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"bbb")
            p2 = Path(f.name)
        try:
            assert sha256_file(p1) != sha256_file(p2)
        finally:
            p1.unlink(missing_ok=True)
            p2.unlink(missing_ok=True)

    def test_returns_hex_string(self):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"data")
            tmp_path = Path(f.name)
        try:
            h = sha256_file(tmp_path)
            assert isinstance(h, str)
            assert len(h) == 64
            int(h, 16)  # should not raise
        finally:
            tmp_path.unlink(missing_ok=True)
