"""Professor downloads beyond the assembled files: all scripts, subtitles, all slide audio."""
from __future__ import annotations

import json
import os
import tempfile
import zipfile
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from starlette.background import BackgroundTask

from lecture_auto.pipeline.subtitles import to_srt, to_vtt
from lecture_auto.web.public import cached_viewer
from lecture_auto.web.settings import Settings


def _attachment(name: str) -> dict[str, str]:
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}


def export_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    def scripts(lid: str) -> list[tuple[int, str]]:
        folder = settings.work_dir / lid / "scripts"
        out = []
        for path in sorted(folder.glob("script_[0-9][0-9][0-9].json")) if folder.is_dir() else []:
            out.append((int(path.stem[-3:]), json.loads(path.read_text(encoding="utf-8")).get("script", "")))
        if not out:
            raise HTTPException(404, "아직 대본이 없습니다")
        return out

    @router.get("/api/lectures/{lid}/export/scripts.txt")
    def scripts_txt(lid: str):
        body = "\n\n".join(f"[슬라이드 {n}]\n{text.strip()}" for n, text in scripts(lid)) + "\n"
        return Response(body, media_type="text/plain; charset=utf-8", headers=_attachment(f"{lid}_대본.txt"))

    @router.get("/api/lectures/{lid}/export/subtitles.{fmt}")
    def subtitles(lid: str, fmt: str):
        if fmt not in ("srt", "vtt"):
            raise HTTPException(404, "자막 형식은 srt 또는 vtt입니다")
        cues = sorted((c["start"], c["end"], c["text"]) for s in cached_viewer(settings, lid)["slides"] for c in s["cues"])
        body = to_srt(cues) if fmt == "srt" else to_vtt(cues)
        media = "application/x-subrip" if fmt == "srt" else "text/vtt"
        return Response(body, media_type=f"{media}; charset=utf-8", headers=_attachment(f"{lid}.{fmt}"))

    @router.get("/api/lectures/{lid}/export/audio.zip")
    def audio_zip(lid: str):
        wavs = sorted((settings.work_dir / lid / "audio").glob("slide_[0-9][0-9][0-9].wav"))
        if not wavs:
            raise HTTPException(404, "아직 음성이 없습니다")
        fd, tmp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
            for wav in wavs:
                zf.write(wav, f"{lid}_{wav.name}")
        return FileResponse(tmp, media_type="application/zip", filename=f"{lid}_음성.zip",
                            background=BackgroundTask(os.unlink, tmp))

    return router
