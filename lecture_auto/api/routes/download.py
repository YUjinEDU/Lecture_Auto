"""Package listing and streaming ZIP download endpoint.

Provides the final deliverable download:
- GET /jobs/{job_id}/package          -- List package contents and sizes
- GET /jobs/{job_id}/package/download -- Stream ZIP of WAVs + merged WAV + MP4 + scripts
"""

import json
from pathlib import Path

import zipstream
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from lecture_auto.schemas.tts import PackageResponse
from lecture_auto.storage.jobs import JobPaths

router = APIRouter(prefix="/jobs", tags=["download"])


def _collect_files(job_paths: JobPaths) -> dict[str, list[Path]]:
    """Collect all deliverable files grouped by category.

    Returns
    -------
    dict
        Keys: ``"slide_wavs"``, ``"merged"``, ``"video"``, ``"scripts"``.
        Values: lists of existing ``Path`` objects.
    """
    result: dict[str, list[Path]] = {
        "slide_wavs": [],
        "merged": [],
        "video": [],
        "scripts": [],
    }

    # Per-slide WAVs (exclude merged)
    if job_paths.audio_dir.exists():
        for wav in sorted(job_paths.audio_dir.glob("audio_*.wav")):
            result["slide_wavs"].append(wav)

    # Merged WAV
    merged = job_paths.audio_dir / "lecture_merged.wav"
    if merged.exists():
        result["merged"].append(merged)

    # MP4 video
    if job_paths.artifacts_dir.exists():
        for mp4 in job_paths.artifacts_dir.glob(f"lecture_*.mp4"):
            result["video"].append(mp4)
            break  # only first match

    # Script JSONs
    if job_paths.scripts_dir.exists():
        for script in sorted(job_paths.scripts_dir.glob("script_*.json")):
            result["scripts"].append(script)

    return result


@router.get("/{job_id}/package", response_model=PackageResponse)
async def list_package(job_id: str):
    """List the contents and total size of the downloadable package.

    Returns 404 if no audio files exist (TTS not yet complete).
    """
    job_paths = JobPaths(job_id)
    collected = _collect_files(job_paths)

    if not collected["slide_wavs"]:
        raise HTTPException(
            status_code=404,
            detail="No audio files found. TTS may not be complete yet.",
        )

    all_files: list[Path] = []
    for group in collected.values():
        all_files.extend(group)

    file_names = [f.name for f in all_files]
    total_bytes = sum(f.stat().st_size for f in all_files)
    total_mb = round(total_bytes / (1024 * 1024), 2)

    return PackageResponse(
        job_id=job_id,
        files=file_names,
        total_size_mb=total_mb,
        download_url=f"/jobs/{job_id}/package/download",
    )


@router.get("/{job_id}/package/download")
async def download_package(job_id: str):
    """Stream a ZIP package containing all deliverables.

    ZIP structure::

        audio/audio_001.wav
        audio/audio_002.wav
        ...
        lecture_merged.wav
        lecture_{job_id}.mp4  (if exists)
        scripts.json          (combined array of all slide scripts)

    Uses ``zipstream-ng`` for streaming generation (no full ZIP in memory).
    WAV/MP4 use ``ZIP_STORED`` compression (already compressed data).
    """
    job_paths = JobPaths(job_id)
    collected = _collect_files(job_paths)

    if not collected["slide_wavs"]:
        raise HTTPException(
            status_code=404,
            detail="No audio files found. TTS may not be complete yet.",
        )

    zs = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_STORED)

    # Per-slide WAVs in audio/ subfolder
    for wav in collected["slide_wavs"]:
        zs.write(str(wav), arcname=f"audio/{wav.name}")

    # Merged WAV at root
    for merged in collected["merged"]:
        zs.write(str(merged), arcname="lecture_merged.wav")

    # MP4 video at root
    for video in collected["video"]:
        zs.write(str(video), arcname=f"lecture_{job_id}.mp4")

    # Combined scripts.json
    if collected["scripts"]:
        scripts_data = []
        for script_path in collected["scripts"]:
            try:
                data = json.loads(script_path.read_text(encoding="utf-8"))
                scripts_data.append(data)
            except (json.JSONDecodeError, OSError):
                continue

        if scripts_data:
            scripts_json = json.dumps(scripts_data, ensure_ascii=False, indent=2)
            zs.writestr("scripts.json", scripts_json.encode("utf-8"))

    return StreamingResponse(
        zs,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="lecture_{job_id}.zip"',
        },
    )
