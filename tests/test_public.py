import json
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lecture_auto.production.study import QuizItem, Study, save_study
from lecture_auto.web.public import make_public_router
from lecture_auto.web.settings import Settings
from lecture_auto.web.shares import (
    create_share,
    list_shares,
    resolve_share,
    revoke_all,
    revoke_share,
)
from tests.test_viewer_study import LID, SENTS, _lecture


@pytest.fixture
def env(tmp_path):
    settings = Settings(root=tmp_path, password="x", secret=b"s" * 32)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pronunciation.yaml").write_text("entries: []\n")
    _lecture(tmp_path, settings.work_dir, settings.output_dir)
    (settings.output_dir / LID / f"{LID}.mp4").write_bytes(b"0123456789" * 100)
    items = {LID: {"id": LID, "name": "시스템 구조", "subject": "종합설계"}}
    reports = []
    app = FastAPI()
    app.include_router(make_public_router(settings, items.get, lambda lid, tok, body: reports.append((lid, tok, body.kind))))
    return settings, TestClient(app), items, reports


def test_share_lifecycle(tmp_path):
    db = tmp_path / "app.db"
    a = create_share(db, "L1", "u1")
    b = create_share(db, "L1", "u1")
    assert a["token"] != b["token"] and len(a["token"]) >= 20
    assert resolve_share(db, a["token"]) == "L1"
    assert not revoke_share(db, "OTHER", a["token"])
    assert revoke_share(db, "L1", a["token"]) and resolve_share(db, a["token"]) is None
    assert revoke_all(db, "L1") == 1 and resolve_share(db, b["token"]) is None
    assert [s["revoked_at"] is not None for s in list_shares(db, "L1")] == [True, True]
    assert resolve_share(db, "") is None and resolve_share(db, "x" * 100) is None


def test_public_lecture_video_and_report(env):
    settings, client, _items, reports = env
    token = create_share(settings.web_dir / "app.db", LID, "u1")["token"]
    page = client.get(f"/w/{token}")
    assert page.status_code == 200 and "watch.js" in page.text
    data = client.get(f"/api/public/{token}").json()
    assert data["title"] == "시스템 구조" and [s["text"] for s in data["viewer"]["slides"][0]["sentences"]] == SENTS
    assert data["study"] == {"glossary": [], "quiz": []}
    part = client.get(f"/api/public/{token}/video", headers={"Range": "bytes=10-19"})
    assert part.status_code == 206 and part.content == b"0123456789"
    assert client.post(f"/api/public/{token}/report", json={"kind": "voice", "text": "제 목소리"}).json() == {"ok": True}
    assert reports == [(LID, token, "voice")]
    assert client.post(f"/api/public/{token}/report", json={"kind": "spam"}).status_code == 422


def test_only_approved_study_items_are_public(env):
    settings, client, _items, _ = env
    token = create_share(settings.web_dir / "app.db", LID, None)["token"]
    q = {"choices": ["a", "b", "c", "d"], "answer": 2}
    save_study(settings.work_dir, Study(lecture_id=LID, quiz=[
        QuizItem(question="공개", approved=True, **q), QuizItem(question="비공개", **q)]))
    assert [x["question"] for x in client.get(f"/api/public/{token}").json()["study"]["quiz"]] == ["공개"]


def test_revoked_unknown_or_removed_lectures_are_404(env):
    settings, client, items, _ = env
    db = settings.web_dir / "app.db"
    token = create_share(db, LID, None)["token"]
    for path in ("/w/nope", "/api/public/nope", "/api/public/nope/video"):
        assert client.get(path).status_code == 404
    items.pop(LID)
    assert client.get(f"/api/public/{token}").status_code == 404
    items[LID] = {"id": LID, "name": "n"}
    revoke_share(db, LID, token)
    assert client.get(f"/w/{token}").status_code == 404


def test_viewer_cache_is_rebuilt_after_reassembly(env):
    settings, client, _items, _ = env
    token = create_share(settings.web_dir / "app.db", LID, None)["token"]
    client.get(f"/api/public/{token}")
    cache = settings.output_dir / LID / f"{LID}.viewer.json"
    tl = settings.output_dir / LID / f"{LID}.timeline.json"
    data = json.loads(tl.read_text())
    data["entries"][0]["start_seconds"] = 20.0
    tl.write_text(json.dumps(data))
    os.utime(cache, (1, 1))
    assert client.get(f"/api/public/{token}").json()["viewer"]["slides"][0]["start"] == 20.0
