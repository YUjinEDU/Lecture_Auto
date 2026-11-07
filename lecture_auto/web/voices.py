from __future__ import annotations

import hashlib
import io
import json
import secrets
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from lecture_auto.pipeline.cache import write_text_atomic
from lecture_auto.web.access import admin_user, current_user
from lecture_auto.web.account_routes import DisabledBody
from lecture_auto.web.accounts import Accounts, timestamp
from lecture_auto.web.quotas import check_storage
from lecture_auto.web.settings import Settings

CONSENT_TEXT = "이 목소리의 주인이 본인이거나, 주인에게 AI 음성 복제 사용 동의를 받았습니다"


class VoiceEdit(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    is_default: bool = False


def voice_path(settings: Settings, uid: str, vid: str) -> Path:
    return Path("data/voices") / uid / f"{vid}.wav"


def validate_ref(settings: Settings, accounts: Accounts, uid: str | None, ref: Path) -> None:
    resolved = (settings.root / ref).resolve()
    builtins = (settings.root / "data/audio_ref").resolve()
    if resolved.is_relative_to(builtins) and resolved.suffix.lower() == ".wav":
        return
    with accounts.connect() as db:
        rows = db.execute("SELECT * FROM voices WHERE user_id=? AND disabled=0", (uid,)).fetchall()
    if any(resolved == (settings.root / voice_path(settings, uid, r["id"])).resolve() for r in rows):
        return
    raise HTTPException(400, "본인의 사용 가능한 음성 또는 기본 참조 음성만 선택할 수 있습니다")


def normalize_audio(data: bytes, suffix: str) -> bytes:
    valid = False
    match suffix:
        case ".wav":
            valid = data[:4] == b"RIFF" and data[8:12] == b"WAVE"
        case ".mp3":
            valid = data.startswith(b"ID3") or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224)
        case ".m4a":
            valid = data[4:8] == b"ftyp"
    if not valid:
        raise HTTPException(400, "WAV, MP3, M4A 파일 내용을 확인해 주세요")
    if suffix == ".wav":
        try:
            with wave.open(io.BytesIO(data), "rb") as audio:
                if audio.getframerate() == 24000 and audio.getnchannels() == 1 and audio.getsampwidth() == 2:
                    if audio.getnframes() == 0 or not audio.readframes(1):
                        raise HTTPException(400, "빈 음성 파일입니다")
                    return data
        except (wave.Error, EOFError):
            raise HTTPException(400, "WAV 파일을 읽을 수 없습니다") from None
    with tempfile.TemporaryDirectory() as tmp:
        source, dest = Path(tmp) / f"source{suffix}", Path(tmp) / "voice.wav"
        source.write_bytes(data)
        try:
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source),
                            "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", str(dest)],
                           check=True, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            raise HTTPException(400, "음성 파일 변환에 실패했습니다") from None
        return dest.read_bytes()


def voices_router(settings: Settings, accounts: Accounts) -> APIRouter:
    router = APIRouter()

    def own(uid: str, vid: str):
        with accounts.connect() as db:
            row = db.execute("SELECT * FROM voices WHERE id=? AND user_id=?", (vid, uid)).fetchone()
        if row is None:
            raise HTTPException(404, "음성을 찾을 수 없습니다")
        return row

    @router.get("/api/voices")
    def listing(request: Request):
        uid = current_user(request).id
        with accounts.connect() as db:
            return [{**dict(r), "ref_voice": str(voice_path(settings, uid, r["id"]))}
                    for r in db.execute("SELECT * FROM voices WHERE user_id=?", (uid,))]

    @router.post("/api/voices")
    def upload(request: Request, file: Annotated[UploadFile, File()],
               consent: Annotated[bool, Form()] = False,
               name: Annotated[str, Form(min_length=1, max_length=100)] = "내 음성"):
        uid = current_user(request).id
        if not settings.raon_enabled:
            raise HTTPException(400, "이 서버는 GPU가 없어 목소리 복제를 쓸 수 없습니다 (Gemini 기본 음성만 사용)")
        if not consent:
            raise HTTPException(400, "음성 복제 사용 동의가 필요합니다")
        data = file.file.read(settings.max_voice_upload_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_voice_upload_mb * 1024 * 1024:
            raise HTTPException(413, "음성 파일 크기 한도를 초과했습니다")
        normalized = normalize_audio(data, Path(file.filename or "").suffix.lower())
        with request.app.state.storage_lock, accounts.connect() as db:
            count = db.execute("SELECT count(*) FROM voices WHERE user_id=?", (uid,)).fetchone()[0]
            limit = accounts.effective_limits(uid)["max_voices"]
            if limit is not None and count >= limit:
                raise HTTPException(409, "등록할 수 있는 음성 개수를 초과했습니다")
            vid, accepted = secrets.token_hex(16), timestamp()
            metadata = {"id": vid, "user_id": uid, "consent_at": accepted, "consent_text": CONSENT_TEXT,
                        "sha256": hashlib.sha256(data).hexdigest(), "name": name.strip()}
            body = json.dumps(metadata, ensure_ascii=False, indent=2)
            check_storage(settings, uid, len(normalized) + len(body.encode()))
            path = settings.root / voice_path(settings, uid, vid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(normalized)
            write_text_atomic(path.with_suffix(".json"), body)
            db.execute("INSERT INTO voices VALUES (?,?,?,?,?,0,?)",
                       (vid, uid, name.strip(), accepted, metadata["sha256"], count == 0))
        return {**metadata, "is_default": count == 0, "disabled": False,
                "ref_voice": str(voice_path(settings, uid, vid))}

    @router.get("/api/voices/{vid}/audio")
    def audio(vid: str, request: Request):
        uid = current_user(request).id
        own(uid, vid)
        return FileResponse(settings.root / voice_path(settings, uid, vid), media_type="audio/wav")

    @router.put("/api/voices/{vid}")
    def edit(vid: str, body: VoiceEdit, request: Request):
        uid = current_user(request).id
        row = own(uid, vid)
        if row["disabled"] and body.is_default:
            raise HTTPException(400, "비활성화된 음성은 기본 음성으로 지정할 수 없습니다")
        with accounts.connect() as db:
            if body.is_default:
                db.execute("UPDATE voices SET is_default=0 WHERE user_id=?", (uid,))
            db.execute("UPDATE voices SET name=?,is_default=? WHERE id=?", (body.name, body.is_default, vid))
        return {"ok": True}

    @router.delete("/api/voices/{vid}")
    def delete(vid: str, request: Request):
        uid = current_user(request).id
        own(uid, vid)
        with request.app.state.storage_lock, accounts.connect() as db:
            db.execute("DELETE FROM voices WHERE id=?", (vid,))
            path = settings.root / voice_path(settings, uid, vid)
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
        return {"ok": True}

    @router.put("/api/admin/voices/{vid}")
    def disable(vid: str, body: DisabledBody, request: Request):
        admin_user(request)
        with accounts.connect() as db:
            if db.execute("SELECT 1 FROM voices WHERE id=?", (vid,)).fetchone() is None:
                raise HTTPException(404, "음성을 찾을 수 없습니다")
            db.execute("UPDATE voices SET disabled=?,is_default=0 WHERE id=?", (body.disabled, vid))
        return {"ok": True}

    return router
