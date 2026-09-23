"""Unit tests for lecture_auto.pipeline.tts module.

Tests use mocked transformers model and tokenizer to avoid GPU dependency.
"""
from __future__ import annotations

import io
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import numpy as np
import pytest
import soundfile as sf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silence_wav(path: Path, duration_seconds: float = 0.1, sample_rate: int = 24000) -> Path:
    """Write a real silence WAV to *path* so soundfile can read it in tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.zeros(int(sample_rate * duration_seconds), dtype=np.float32)
    sf.write(str(path), samples, sample_rate)
    return path


# ---------------------------------------------------------------------------
# Import the module under test (must not require GPU at import time)
# ---------------------------------------------------------------------------

import lecture_auto.pipeline.tts as tts_module
from lecture_auto.pipeline.tts import (
    load_tts,
    synthesize_audio,
    synthesize_slide,
    generate_silence,
    merge_audio,
)


# ---------------------------------------------------------------------------
# Test 1: synthesize_audio returns list[Path]
# ---------------------------------------------------------------------------

def test_synthesize_audio_returns_list_of_paths(tmp_path):
    """synthesize_audio must return a list of Path objects, one per script."""
    mock_model = MagicMock()
    mock_model.__class__.__name__ = "MockTTSModel"

    scripts = [
        {"slide_number": 1, "script": "Hello world."},
        {"slide_number": 2, "script": "Second slide text."},
    ]

    with patch.object(tts_module, "synthesize_slide") as mock_slide:
        mock_slide.side_effect = lambda model, text, output_path, voice_ref_path=None: output_path
        result = synthesize_audio(mock_model, scripts, tmp_path)

    assert isinstance(result, list)
    assert len(result) == 2
    for item in result:
        assert isinstance(item, Path)


# ---------------------------------------------------------------------------
# Test 2: Output WAV files named audio_001.wav, audio_002.wav
# ---------------------------------------------------------------------------

def test_synthesize_audio_file_naming(tmp_path):
    """Output WAV files must be named audio_NNN.wav using 3-digit zero-padding."""
    mock_model = MagicMock()
    scripts = [
        {"slide_number": 1, "script": "Slide one."},
        {"slide_number": 2, "script": "Slide two."},
        {"slide_number": 3, "script": "Slide three."},
    ]

    with patch.object(tts_module, "synthesize_slide") as mock_slide:
        mock_slide.side_effect = lambda model, text, output_path, voice_ref_path=None: output_path
        result = synthesize_audio(mock_model, scripts, tmp_path)

    names = [p.name for p in result]
    assert "audio_001.wav" in names
    assert "audio_002.wav" in names
    assert "audio_003.wav" in names


# ---------------------------------------------------------------------------
# Test 3: load_tts accepts model_path with default
# ---------------------------------------------------------------------------

def test_load_tts_signature():
    """load_tts must accept model_path with default 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'."""
    sig = inspect.signature(load_tts)
    params = sig.parameters
    assert "model_path" in params
    default = params["model_path"].default
    assert default == "Qwen/Qwen3-TTS-12Hz-1.7B-Base"


def test_load_tts_returns_qwen_model():
    """load_tts returns the Qwen3TTSModel instance from the qwen-tts package.

    (The previous transformers-based dict return — model + tokenizer — is
    obsolete: qwen-tts exposes a single model object with voice-clone methods.)
    """
    fake_model = MagicMock()

    with patch.object(tts_module, "Qwen3TTSModel") as mock_model_cls:
        mock_model_cls.from_pretrained.return_value = fake_model

        result = load_tts("some/model/path")

    assert result is fake_model
    mock_model_cls.from_pretrained.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: voice_ref_path is passed to synthesize_slide when provided
# ---------------------------------------------------------------------------

def test_voice_ref_path_passed_to_synthesize_slide(tmp_path):
    """When voice_ref_path is provided, it must be forwarded to each synthesize_slide call."""
    mock_model = MagicMock()
    voice_ref = tmp_path / "voice.wav"
    _make_silence_wav(voice_ref)

    scripts = [{"slide_number": 1, "script": "Test text."}]

    with patch.object(tts_module, "synthesize_slide") as mock_slide:
        mock_slide.side_effect = lambda model, text, output_path, voice_ref_path=None: output_path
        synthesize_audio(mock_model, scripts, tmp_path, voice_ref_path=voice_ref)

    assert mock_slide.call_count == 1
    _, kwargs = mock_slide.call_args
    # voice_ref_path may be passed as positional or keyword
    call_args = mock_slide.call_args
    # Check it appears somewhere in the call
    assert voice_ref in call_args.args or call_args.kwargs.get("voice_ref_path") == voice_ref


# ---------------------------------------------------------------------------
# Test 5: When voice_ref_path is None, default voice is used
# ---------------------------------------------------------------------------

def test_no_voice_ref_uses_default(tmp_path):
    """When voice_ref_path is None, synthesize_slide receives None."""
    mock_model = MagicMock()
    scripts = [{"slide_number": 1, "script": "Default voice."}]

    with patch.object(tts_module, "synthesize_slide") as mock_slide:
        mock_slide.side_effect = lambda model, text, output_path, voice_ref_path=None: output_path
        synthesize_audio(mock_model, scripts, tmp_path, voice_ref_path=None)

    call_args = mock_slide.call_args
    voice_arg = call_args.kwargs.get("voice_ref_path", call_args.args[3] if len(call_args.args) > 3 else None)
    assert voice_arg is None


# ---------------------------------------------------------------------------
# Test 6: Empty script text produces a short silence WAV (not an error)
# ---------------------------------------------------------------------------

def test_empty_script_produces_silence(tmp_path):
    """synthesize_slide with empty text must write a silence WAV without raising."""
    mock_tts = {"model": MagicMock(), "tokenizer": MagicMock()}
    output_path = tmp_path / "audio_001.wav"

    result = synthesize_slide(mock_tts, "", output_path)

    assert result == output_path
    assert output_path.exists()
    data, sr = sf.read(str(output_path))
    assert sr == 24000
    assert len(data) > 0
    # Silence: all samples near zero
    assert np.abs(data).max() < 1e-6


def test_whitespace_only_script_produces_silence(tmp_path):
    """synthesize_slide with whitespace-only text must also write silence."""
    mock_tts = {"model": MagicMock(), "tokenizer": MagicMock()}
    output_path = tmp_path / "audio_002.wav"

    result = synthesize_slide(mock_tts, "   \n\t  ", output_path)

    assert result == output_path
    assert output_path.exists()


# ---------------------------------------------------------------------------
# Test 7: Each slide's script text is passed individually
# ---------------------------------------------------------------------------

def test_each_slide_script_passed_individually(tmp_path):
    """Each script entry must result in exactly one synthesize_slide call with its text."""
    mock_model = MagicMock()
    scripts = [
        {"slide_number": 1, "script": "First slide."},
        {"slide_number": 2, "script": "Second slide."},
    ]

    with patch.object(tts_module, "synthesize_slide") as mock_slide:
        mock_slide.side_effect = lambda model, text, output_path, voice_ref_path=None: output_path
        synthesize_audio(mock_model, scripts, tmp_path)

    assert mock_slide.call_count == 2
    texts_passed = [c.args[1] for c in mock_slide.call_args_list]
    assert "First slide." in texts_passed
    assert "Second slide." in texts_passed


# ---------------------------------------------------------------------------
# Additional: generate_silence produces valid WAV
# ---------------------------------------------------------------------------

def test_generate_silence(tmp_path):
    """generate_silence must create a WAV of the requested duration."""
    output_path = tmp_path / "silence.wav"
    result = generate_silence(1.0, sample_rate=24000)
    assert isinstance(result, np.ndarray)
    assert len(result) == 24000
    assert np.abs(result).max() < 1e-6


# ---------------------------------------------------------------------------
# S1-a: merge_audio(list) merges exactly the given files, no glob
# ---------------------------------------------------------------------------

def test_merge_audio_list_form_ignores_unrelated_files_in_dir(tmp_path):
    """When given an explicit WAV list, merge_audio must merge only those
    files (in that order), even if the directory also contains an unrelated
    WAV that would otherwise glob-match."""
    audio_dir = tmp_path / "audio"
    wav1 = _make_silence_wav(audio_dir / "slide_001.wav", duration_seconds=0.1)
    wav2 = _make_silence_wav(audio_dir / "slide_002.wav", duration_seconds=0.2)
    # Unrelated file in the same directory -- must NOT be included.
    _make_silence_wav(audio_dir / "slide_999.wav", duration_seconds=5.0)

    out = tmp_path / "merged.wav"
    result = merge_audio([wav1, wav2], out)

    assert result == out
    merged, sr = sf.read(str(out))
    expected_len = int(24000 * 0.1) + int(24000 * 0.2)
    assert len(merged) == expected_len


def test_merge_audio_directory_form_still_globs(tmp_path):
    """Passing a directory (not a list) keeps the existing glob-based behavior."""
    audio_dir = tmp_path / "audio"
    _make_silence_wav(audio_dir / "slide_001.wav", duration_seconds=0.1)
    _make_silence_wav(audio_dir / "slide_002.wav", duration_seconds=0.2)

    out = tmp_path / "merged.wav"
    merge_audio(audio_dir, out)

    merged, sr = sf.read(str(out))
    expected_len = int(24000 * 0.1) + int(24000 * 0.2)
    assert len(merged) == expected_len


def test_merge_audio_empty_list_raises(tmp_path):
    """An empty explicit list has nothing to merge -- must raise, not write
    an empty/garbage output file."""
    out = tmp_path / "merged.wav"
    with pytest.raises(FileNotFoundError):
        merge_audio([], out)
