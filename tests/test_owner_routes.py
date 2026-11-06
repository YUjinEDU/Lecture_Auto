import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from lecture_auto.production.study import load_study
from lecture_auto.web.owner_routes import make_owner_router
from lecture_auto.web.settings import Settings
from lecture_auto.web.shares import resolve_share
from tests.test_viewer_study import LID, _lecture

QUIZ = {"question": "q", "choices": ["a", "b", "c", "d"], "answer": 3, "approved": True}


@pytest.fixture
def env(tmp_path):
    settings = Settings(root=tmp_path, password="x", secret=b"s" * 32)
    owners = {LID: "alice", "88_other": "bob"}

    def owned(request, lecture_id):
        if owners.get(lecture_id) != request.headers.get("x-user"):
            raise HTTPException(404, "강의를 찾을 수 없습니다")
        return {"id": lecture_id}

    app = FastAPI()
    app.include_router(make_owner_router(settings, owned, lambda r: r.headers.get("x-user")))
    return settings, TestClient(app, headers={"x-user": "alice"})


def test_share_needs_a_built_video_then_can_be_revoked(env, tmp_path):
    settings, c = env
    assert c.post(f"/api/lectures/{LID}/shares").status_code == 409
    _lecture(tmp_path, settings.work_dir, settings.output_dir)
    share = c.post(f"/api/lectures/{LID}/shares").json()
    assert share["path"] == f"w/{share['token']}" and not share["revoked"]
    assert resolve_share(settings.web_dir / "app.db", share["token"]) == LID
    assert [s["token"] for s in c.get(f"/api/lectures/{LID}/shares").json()] == [share["token"]]
    assert c.delete(f"/api/lectures/{LID}/shares/{share['token']}").json() == {"ok": True}
    assert c.delete(f"/api/lectures/{LID}/shares/{share['token']}").status_code == 404
    assert resolve_share(settings.web_dir / "app.db", share["token"]) is None


def test_other_users_lecture_is_404(env):
    _, c = env
    for method, path in (("get", "/api/lectures/88_other/shares"), ("post", "/api/lectures/88_other/shares"),
                         ("get", "/api/lectures/88_other/study")):
        assert getattr(c, method)(path).status_code == 404
    assert c.put("/api/lectures/88_other/study", json={"glossary": [], "quiz": []}).status_code == 404


def test_study_edit_round_trip_and_validation(env):
    settings, c = env
    assert c.get(f"/api/lectures/{LID}/study").json()["quiz"] == []
    saved = c.put(f"/api/lectures/{LID}/study", json={
        "glossary": [{"term": "스크럼", "definition": "고친 설명", "approved": True}], "quiz": [QUIZ]}).json()
    assert saved["glossary"][0]["definition"] == "고친 설명"
    assert load_study(settings.work_dir, LID).public()["quiz"][0]["answer"] == 3
    bad = {**QUIZ, "choices": ["a", "b"]}
    assert c.put(f"/api/lectures/{LID}/study", json={"quiz": [bad]}).status_code == 422
