from __future__ import annotations

import json
from pathlib import Path

import zipstream
from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from lecture_auto.demo import (
    _resolve_voice_reference,
    create_demo_job,
    get_demo_job_paths,
    launch_demo_pipeline,
    launch_rerun,
    request_stop,
    rerun_tts_only,
    rerun_video_only,
    restore_all_jobs_from_disk,
    restore_job_from_disk,
    save_uploaded_pdf,
    save_voice_reference,
    update_glossary,
    update_script_and_rebuild,
)
from lecture_auto.demo.state import delete_job, get_job, list_job_summaries, rename_job, upsert_slide


router = APIRouter(tags=["demo"])


def _require_job(job_id: str) -> dict:
    job = get_job(job_id) or restore_job_from_disk(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Demo job not found: {job_id}")
    return job


@router.get("/demo")
async def demo_page():
    index_path = Path(__file__).resolve().parents[2] / "demo_static" / "index.html"
    return FileResponse(index_path)


@router.get("/demo/api/jobs")
async def get_demo_jobs():
    restore_all_jobs_from_disk()
    return JSONResponse(list_job_summaries())


@router.post("/demo/api/jobs")
async def create_demo_pipeline_job(
    pdf_file: UploadFile = File(...),
    lecture_name: str = Form("Local Lecture Auto Demo"),
    target_minutes: int = Form(8),
    audience: str = Form("학부 전공"),
    explanation_style: str = Form("개념 중심"),
    lecture_density: str = Form("표준형"),
    learner_profile: str = Form(""),
    delivery_notes: str = Form(""),
    use_vlm: bool = Form(True),
):
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Demo currently accepts PDF uploads only.")

    content = await pdf_file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded PDF is empty.")

    settings = {
        "audience": audience,
        "explanation_style": explanation_style,
        "lecture_density": lecture_density,
        "learner_profile": learner_profile,
        "delivery_notes": delivery_notes,
        "use_vlm": use_vlm,
    }
    job = create_demo_job(pdf_file.filename, lecture_name, target_minutes, settings=settings)
    pdf_path = save_uploaded_pdf(job["job_id"], pdf_file.filename, content)
    launch_demo_pipeline(job["job_id"], pdf_path, lecture_name, target_minutes)
    return JSONResponse(job)


@router.get("/demo/api/jobs/{job_id}")
async def get_demo_pipeline_job(job_id: str):
    return JSONResponse(_require_job(job_id))


@router.delete("/demo/api/jobs/{job_id}")
async def delete_demo_job(job_id: str):
    import shutil
    # Delete from memory
    delete_job(job_id)
    # Delete from disk so restore_all_jobs_from_disk won't revive it
    job_dir = get_demo_job_paths(job_id).job_dir
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return {"job_id": job_id, "deleted": True}


@router.patch("/demo/api/jobs/{job_id}")
async def patch_demo_job(job_id: str, payload: dict = Body(...)):
    new_name = payload.get("lecture_name")
    if not new_name or not isinstance(new_name, str):
        raise HTTPException(status_code=400, detail="lecture_name is required.")
    result = rename_job(job_id, new_name.strip())
    if result is None:
        raise HTTPException(status_code=404, detail=f"Demo job not found: {job_id}")
    return JSONResponse(result)


@router.post("/demo/api/jobs/{job_id}/voice-reference")
async def upload_voice_reference(job_id: str, audio_file: UploadFile = File(...)):
    _require_job(job_id)
    content = await audio_file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded audio is empty.")
    path = save_voice_reference(job_id, audio_file.filename or "voice_reference.webm", content)
    return {"job_id": job_id, "voice_reference": path.name}


@router.get("/demo/api/jobs/{job_id}/voice-reference")
async def get_voice_reference(job_id: str):
    _require_job(job_id)
    voice_path, _ = _resolve_voice_reference(job_id)
    if voice_path is None or not voice_path.exists():
        raise HTTPException(status_code=404, detail="Voice reference not found.")
    media_type = "audio/wav" if voice_path.suffix.lower() == ".wav" else "audio/webm"
    return FileResponse(voice_path, media_type=media_type)


@router.put("/demo/api/jobs/{job_id}/slides/{slide_number}/script")
async def update_slide_script(
    job_id: str,
    slide_number: int,
    payload: dict = Body(...),
):
    _require_job(job_id)
    script_raw = payload.get("script")
    if script_raw is not None and not isinstance(script_raw, str):
        raise HTTPException(status_code=422, detail="'script' must be a string.")
    script_text = (script_raw or "").strip()
    if not script_text:
        raise HTTPException(status_code=400, detail="Script text is required.")
    updated = update_script_and_rebuild(job_id, slide_number, script_text)
    return {"job_id": job_id, "slide_number": slide_number, "script": updated}


@router.post("/demo/api/jobs/{job_id}/rerun")
async def rerun_demo_job(job_id: str, payload: dict = Body(default={})):
    job = _require_job(job_id)
    target_minutes = payload.get("target_minutes", job.get("target_minutes"))
    settings_updates = {
        key: value
        for key, value in payload.items()
        if key in {"audience", "explanation_style", "lecture_density", "learner_profile", "delivery_notes", "use_vlm"}
    }
    launch_rerun(job_id, int(target_minutes) if target_minutes else None, settings_updates or None)
    return {"job_id": job_id, "status": "rerunning", "target_minutes": target_minutes, "settings_updates": settings_updates}


@router.post("/demo/api/jobs/{job_id}/stop")
async def stop_demo_job(job_id: str):
    _require_job(job_id)
    request_stop(job_id)
    return {"job_id": job_id, "status": "stop_requested"}


@router.put("/demo/api/jobs/{job_id}/glossary")
async def update_demo_glossary(job_id: str, payload: dict = Body(...)):
    _require_job(job_id)
    glossary = payload.get("glossary") or {}
    if not isinstance(glossary, dict):
        raise HTTPException(status_code=400, detail="Glossary must be an object.")
    updated = update_glossary(job_id, glossary)
    return {"job_id": job_id, "glossary": updated}


@router.post("/demo/api/jobs/{job_id}/actions/rerun-tts")
async def rerun_demo_tts(job_id: str, payload: dict = Body(default={})):
    _require_job(job_id)
    rerun_tts_only(job_id, payload.get("slide_number"))
    return {"job_id": job_id, "status": "reran-tts", "slide_number": payload.get("slide_number")}


@router.post("/demo/api/jobs/{job_id}/actions/rerun-video")
async def rerun_demo_video(job_id: str):
    _require_job(job_id)
    rerun_video_only(job_id)
    return {"job_id": job_id, "status": "reran-video"}


@router.post("/demo/api/jobs/{job_id}/slides/{slide_number}/approve")
async def approve_slide(job_id: str, slide_number: int):
    _require_job(job_id)
    upsert_slide(job_id, slide_number, {"approved": True, "tts_status": "queued"})
    rerun_tts_only(job_id, slide_number)
    return {"status": "ok", "slide": slide_number, "tts": "queued"}


@router.get("/demo/api/jobs/{job_id}/slides/{slide_number}/png")
async def get_demo_slide(job_id: str, slide_number: int):
    _require_job(job_id)
    job_paths = get_demo_job_paths(job_id)
    slide_path = job_paths.rendered_dir / f"slide_{slide_number:03d}.png"
    if not slide_path.exists():
        raise HTTPException(status_code=404, detail="Slide preview not found.")
    return FileResponse(slide_path, media_type="image/png")


@router.get("/demo/api/jobs/{job_id}/audio/{slide_number}/wav")
async def get_demo_audio(job_id: str, slide_number: int):
    _require_job(job_id)
    job_paths = get_demo_job_paths(job_id)
    wav_path = job_paths.audio_dir / f"audio_{slide_number:03d}.wav"
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail="Slide audio not found.")
    return FileResponse(wav_path, media_type="audio/wav")


@router.get("/demo/api/jobs/{job_id}/audio/merged")
async def get_demo_merged_audio(job_id: str):
    _require_job(job_id)
    job_paths = get_demo_job_paths(job_id)
    wav_path = job_paths.audio_dir / "lecture_merged.wav"
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail="Merged audio not found.")
    return FileResponse(wav_path, media_type="audio/wav")


@router.get("/demo/api/jobs/{job_id}/video")
async def get_demo_video(job_id: str):
    _require_job(job_id)
    job_paths = get_demo_job_paths(job_id)
    matches = list(job_paths.artifacts_dir.glob("lecture_*.mp4"))
    if not matches:
        raise HTTPException(status_code=404, detail="Lecture video not found.")
    return FileResponse(matches[0], media_type="video/mp4")


@router.get("/demo/api/jobs/{job_id}/package")
async def get_demo_package(job_id: str):
    job = _require_job(job_id)
    job_paths = get_demo_job_paths(job_id)
    files = []
    for path in sorted(job_paths.audio_dir.glob("*.wav")):
        files.append({"name": path.name, "bytes": path.stat().st_size})
    for path in sorted(job_paths.artifacts_dir.glob("*.mp4")):
        files.append({"name": path.name, "bytes": path.stat().st_size})
    for path in sorted(job_paths.scripts_dir.glob("script_*.json")):
        files.append({"name": path.name, "bytes": path.stat().st_size})
    return {"job_id": job_id, "status": job["status"], "files": files}


@router.get("/demo/api/jobs/{job_id}/package/download")
async def download_demo_package(job_id: str):
    _require_job(job_id)
    job_paths = get_demo_job_paths(job_id)
    if not job_paths.audio_dir.exists():
        raise HTTPException(status_code=404, detail="Package is not ready.")

    zs = zipstream.ZipFile(mode="w", compression=zipstream.ZIP_STORED)

    for wav in sorted(job_paths.audio_dir.glob("audio_*.wav")):
        zs.write(str(wav), arcname=f"audio/{wav.name}")

    merged = job_paths.audio_dir / "lecture_merged.wav"
    if merged.exists():
        zs.write(str(merged), arcname="lecture_merged.wav")

    for mp4 in sorted(job_paths.artifacts_dir.glob("lecture_*.mp4")):
        zs.write(str(mp4), arcname=mp4.name)

    scripts = []
    for script_path in sorted(job_paths.scripts_dir.glob("script_*.json")):
        try:
            scripts.append(json.loads(script_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    if scripts:
        zs.writestr(
            "scripts.json",
            json.dumps(scripts, ensure_ascii=False, indent=2).encode("utf-8"),
        )

    return StreamingResponse(
        zs,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="lecture_demo_{job_id}.zip"'},
    )
