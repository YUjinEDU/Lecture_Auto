from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf


_PATH = Path(__file__).parents[1] / "scripts" / "build_voice_reference.py"
_SPEC = importlib.util.spec_from_file_location("build_voice_reference", _PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_reference = _MODULE.build_reference


def test_build_reference_writes_audio_and_provenance(tmp_path: Path):
    source = tmp_path / "source.wav"
    output = tmp_path / "reference.wav"
    sr = 16000
    tone = 0.2 * np.sin(2 * np.pi * 220 * np.arange(sr * 3) / sr)
    sf.write(source, tone, sr)

    build_reference(source, output, 0.5, 2.5)

    info = sf.info(output)
    metadata = json.loads(output.with_suffix(".wav.json").read_text(encoding="utf-8"))
    assert (info.samplerate, info.channels) == (24000, 1)
    assert 1 <= info.duration <= 2.1
    assert metadata["source_sha256"]
    assert metadata["output_sha256"]
    assert metadata["start_seconds"] == 0.5
    assert metadata["end_seconds"] == 2.5


def test_build_reference_rejects_invalid_or_overlong_range(tmp_path: Path):
    source = tmp_path / "source.wav"
    sf.write(source, np.ones(16000, dtype=np.float32) * 0.1, 16000)

    with pytest.raises(ValueError):
        build_reference(source, tmp_path / "bad.wav", 3, 2)
    with pytest.raises(ValueError, match="at most 10 seconds"):
        build_reference(source, tmp_path / "bad.wav", 0, 11)
