"""Build a reproducible Raon speaker reference from a recorded lecture.

Example:
    uv run python scripts/build_voice_reference.py \
      data/audio_ref/professor_past_lecture_2025.wav \
      data/audio_ref/reference_v1.wav --start 123.4 --end 132.8
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import soundfile as sf


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_reference(
    source: Path, output: Path, start: float, end: float, clean_studio: bool = False
) -> Path:
    if not source.is_file():
        raise FileNotFoundError(source)
    if start < 0 or end <= start:
        raise ValueError("--start must be >= 0 and --end must be greater than --start")
    if end - start > 10:
        raise ValueError("Raon uses at most 10 seconds; select a reference no longer than 10 seconds")

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp.wav")

    # Base filter chain: trim edges only, preserving natural speech pauses
    filter_parts = [
        "silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB",
        "areverse",
        "silenceremove=start_periods=1:start_duration=0:start_threshold=-45dB",
        "areverse",
    ]

    # S21 Studio cleaning: HPF 80Hz, FFT denoiser (-12dB), anti-boxiness 320Hz, presence 3kHz
    if clean_studio:
        filter_parts.extend([
            "highpass=f=80",
            "afftdn=nr=12:nf=-38:tn=1",
            "equalizer=f=320:width_type=q:w=1.2:g=-1.8",
            "equalizer=f=3000:width_type=q:w=1.0:g=1.5",
        ])

    filter_parts.append("loudnorm=I=-23:TP=-2:LRA=7")
    af_string = ",".join(filter_parts)

    command = [
        "ffmpeg", "-nostdin", "-y", "-v", "error",
        "-ss", f"{start:.6f}", "-to", f"{end:.6f}", "-i", str(source),
        "-af", af_string,
        "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(tmp),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")

    info = sf.info(tmp)
    if not 1 <= info.duration <= 10 or info.samplerate != 24000 or info.channels != 1:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"invalid reference output: {info}")
    tmp.replace(output)

    version = subprocess.run(
        ["ffmpeg", "-version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()[0]
    provenance = {
        "source": str(source.resolve()),
        "source_sha256": _sha256(source),
        "start_seconds": start,
        "end_seconds": end,
        "processing": command[command.index("-af") + 1],
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "duration_seconds": info.duration,
        "ffmpeg": version,
        "output_sha256": _sha256(output),
    }
    metadata = output.with_suffix(output.suffix + ".json")
    metadata_tmp = metadata.with_name(metadata.name + ".tmp")
    metadata_tmp.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    metadata_tmp.replace(metadata)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument(
        "--clean-studio",
        action="store_true",
        help="Apply S21 studio cleaning (HPF 80Hz + FFT denoiser + anti-boxiness EQ)",
    )
    args = parser.parse_args()
    built = build_reference(
        args.source, args.output, args.start, args.end, clean_studio=args.clean_studio
    )
    print(f"built {built} ({built.with_suffix(built.suffix + '.json')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
