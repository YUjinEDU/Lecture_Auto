"""Owner-only routes for sharing a lecture and curating its glossary/quiz."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from lecture_auto.production.study import (
    GlossaryItem,
    QuizItem,
    Study,
    load_study,
    save_study,
)
from lecture_auto.web.settings import Settings
from lecture_auto.web.shares import create_share, list_shares, revoke_share


class StudyBody(BaseModel):
    glossary: list[GlossaryItem] = Field(default_factory=list, max_length=200)
    quiz: list[QuizItem] = Field(default_factory=list, max_length=200)


def make_owner_router(
    settings: Settings,
    owned_lecture: Callable[[Request, str], dict],
    current_user_id: Callable[[Request], str | None],
    auth_dependencies: list | None = None,
) -> APIRouter:
    """``owned_lecture(request, lecture_id)`` returns the lecture or raises 404 when the caller may
    not manage it; ``current_user_id`` records who created a share link."""
    router = APIRouter(dependencies=auth_dependencies or [])
    db = settings.web_dir / "app.db"

    def share_view(row: dict) -> dict:
        return {"token": row["token"], "path": f"w/{row['token']}", "created_at": row["created_at"],
                "revoked": row["revoked_at"] is not None}

    @router.get("/api/lectures/{lecture_id}/shares")
    def shares(lecture_id: str, request: Request):
        owned_lecture(request, lecture_id)
        return [share_view(r) for r in list_shares(db, lecture_id)]

    @router.post("/api/lectures/{lecture_id}/shares")
    def new_share(lecture_id: str, request: Request):
        owned_lecture(request, lecture_id)
        out = settings.output_dir / lecture_id
        if not out.is_dir() or not any(out.glob("*.timeline.json")):
            raise HTTPException(409, "영상을 먼저 만든 뒤에 공유할 수 있습니다")
        row = create_share(db, lecture_id, current_user_id(request))
        return share_view({**row, "created_at": None})

    @router.delete("/api/lectures/{lecture_id}/shares/{token}")
    def delete_share(lecture_id: str, token: str, request: Request):
        owned_lecture(request, lecture_id)
        if not revoke_share(db, lecture_id, token):
            raise HTTPException(404, "공유 링크가 없습니다")
        return {"ok": True}

    @router.get("/api/lectures/{lecture_id}/study")
    def study(lecture_id: str, request: Request):
        owned_lecture(request, lecture_id)
        return load_study(settings.work_dir, lecture_id).model_dump(mode="json")

    @router.put("/api/lectures/{lecture_id}/study")
    def put_study(lecture_id: str, body: StudyBody, request: Request):
        owned_lecture(request, lecture_id)
        previous = load_study(settings.work_dir, lecture_id)
        updated = Study(lecture_id=lecture_id, glossary=body.glossary, quiz=body.quiz, generated_at=previous.generated_at)
        save_study(settings.work_dir, updated)
        return updated.model_dump(mode="json")

    return router

