from __future__ import annotations

from fastapi import HTTPException

from lecture_auto.core.project import load_projects
from lecture_auto.web.accounts import Accounts
from lecture_auto.web.settings import Settings


def storage_bytes(settings: Settings, uid: str) -> int:
    accounts = Accounts(settings)
    with accounts.connect() as db:
        ids = {row["lecture_id"] for row in db.execute(
            "SELECT lecture_id FROM upload_owners WHERE user_id=?", (uid,))}
    ids.update(p.id for p in load_projects(settings.projects_dir) if p.owner == uid)
    folders = [settings.uploads_dir / lid for lid in ids]
    folders.append(settings.root / "data" / "voices" / uid)
    return sum(p.stat().st_size for folder in folders for p in folder.rglob("*") if p.is_file())


def check_storage(settings: Settings, uid: str, incoming: int) -> None:
    if storage_bytes(settings, uid) + incoming > settings.storage_limit_mb * 1024 * 1024:
        raise HTTPException(413, "계정 저장 공간 한도를 초과했습니다. 파일을 정리해 주세요")
