"""Private transcript upload and account-owned profile management."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import ValidationError

from lecture_auto.llm import OpenAILLMClient
from lecture_auto.pipeline.style_profile import (
    MAX_TRANSCRIPT_BYTES,
    TranscriptError,
    build_style_profile,
)
from lecture_auto.production.style_profiles import ProfileNotFound, StyleProfiles
from lecture_auto.web.access import current_user
from lecture_auto.web.accounts import Accounts
from lecture_auto.web.settings import Settings


def style_profiles_router(settings: Settings, accounts: Accounts) -> APIRouter:
    router = APIRouter()

    @router.get("/api/style-profiles")
    def listing(request: Request):
        return StyleProfiles(settings.root, current_user(request).id).listing()

    @router.post("/api/style-profiles")
    def upload(request: Request, file: Annotated[UploadFile, File()]):
        user = current_user(request)
        if Path(file.filename or "").suffix.lower() != ".txt":
            raise HTTPException(400, "TXT 녹취록만 올릴 수 있습니다")
        data = file.file.read(MAX_TRANSCRIPT_BYTES + 1)
        if len(data) > MAX_TRANSCRIPT_BYTES:
            raise HTTPException(413, "녹취록은 2 MB 이하여야 합니다")
        try:
            transcript = data.decode("utf-8-sig")
        except UnicodeError:
            raise HTTPException(400, "UTF-8 TXT 파일로 저장해 주세요") from None
        key = accounts.api_key(user.id)
        if not key and user.role != "admin":
            raise HTTPException(400, "설정에서 본인의 BAZE API 키를 등록해 주세요")
        client = OpenAILLMClient(**({"api_key": key, "base_url": "https://factchat-cloud.mindlogic.ai/v1/gateway"}
                                   if key else {}))
        try:
            profile = build_style_profile(client, transcript)
        except (TranscriptError, ValidationError):
            raise HTTPException(400, "녹취록에서 말투를 추출하지 못했습니다. 내용을 확인해 주세요") from None
        profile = profile.model_copy(update={"name": Path(file.filename).stem[:100]})
        with request.app.state.storage_lock:
            profile_id = StyleProfiles(settings.root, user.id).save(profile)
        return {"id": profile_id, "name": profile.name, "compact": profile.compact()}

    @router.delete("/api/style-profiles/{profile_id}")
    def delete(profile_id: str, request: Request):
        with request.app.state.storage_lock:
            try:
                StyleProfiles(settings.root, current_user(request).id).delete(profile_id)
            except ProfileNotFound:
                raise HTTPException(404, "말투 프로필을 찾을 수 없습니다") from None
        return {"ok": True}

    return router
