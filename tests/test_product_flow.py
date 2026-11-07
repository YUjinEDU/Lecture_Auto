import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lecture_auto.core.project import ProjectConfig, save_project
from lecture_auto.web.app import create_app
from lecture_auto.web.settings import Settings
from tests.test_viewer_study import LID, SENTS, _lecture

ROOT = Path(__file__).resolve().parent.parent
QUIZ = {"question": "공개 문항", "choices": ["a", "b", "c", "d"], "answer": 1, "approved": True}


@pytest.fixture
def app_env(tmp_path):
    root = tmp_path / "root"
    shutil.copytree(ROOT / "config", root / "config")
    settings = Settings(root=root, password="admin-pass-123", secret=b"s" * 32, signup_mode="open")
    _lecture(tmp_path, settings.work_dir, settings.output_dir)
    (settings.output_dir / LID / f"{LID}.mp4").write_bytes(b"x" * 64)
    save_project(ProjectConfig(id=LID, name="시스템 구조", subject="종합설계"), settings.projects_dir)
    app = create_app(settings)
    with TestClient(app) as admin:
        student, other = TestClient(app), TestClient(app)
        assert admin.post("/api/login", json={"password": "admin-pass-123"}).status_code == 200
        yield settings, app, admin, student, other


def test_share_public_page_report_and_takedown(app_env):
    _settings, app, admin, student, _other = app_env
    share = admin.post(f"/api/lectures/{LID}/shares").json()
    token = share["token"]
    assert admin.put(f"/api/lectures/{LID}/study", json={"quiz": [QUIZ]}).status_code == 200

    page = student.get(f"/w/{token}")
    assert page.status_code == 200 and "watch.js" in page.text
    data = student.get(f"/api/public/{token}").json()
    assert data["title"] == "시스템 구조"
    assert [s["text"] for s in data["viewer"]["slides"][0]["sentences"]] == SENTS
    assert [q["question"] for q in data["study"]["quiz"]] == ["공개 문항"]
    assert student.get(f"/api/public/{token}/video").status_code == 200
    assert student.get(f"/api/lectures/{LID}").status_code == 401

    assert student.post(f"/api/public/{token}/report", json={"kind": "voice", "text": "제 목소리 같아요", "at_seconds": 75}).json() == {"ok": True}
    [report] = app.state.accounts.reports()
    assert report["target_id"] == LID and "1분 15초" in report["reason"] and "제 목소리" in report["reason"]

    app.state.accounts.disable_resource("lecture", LID, True)
    assert student.get(f"/api/public/{token}").status_code == 404
    app.state.accounts.disable_resource("lecture", LID, False)
    assert admin.delete(f"/api/lectures/{LID}/shares/{token}").json() == {"ok": True}
    assert student.get(f"/w/{token}").status_code == 404


def test_other_users_cannot_share_or_edit_someone_elses_lecture(app_env):
    _settings, _app, _admin, _student, other = app_env
    signup = other.post("/api/signup", json={
        "email": "b@example.com", "password": "password-1234", "display_name": "B", "terms_accepted": True})
    assert signup.status_code in (200, 201), signup.text
    assert other.post("/api/login", json={"email": "b@example.com", "password": "password-1234"}).status_code == 200
    assert other.post(f"/api/lectures/{LID}/shares").status_code == 404
    assert other.get(f"/api/lectures/{LID}/study").status_code == 404
    assert other.put(f"/api/lectures/{LID}/study", json={"quiz": []}).status_code == 404


def test_study_is_a_known_job_kind(app_env):
    _settings, app, admin, _student, _other = app_env
    res = admin.post(f"/api/lectures/{LID}/jobs", json={"kind": "study"})
    assert res.status_code == 200, res.text
    assert res.json()["label"] == "용어·퀴즈 초안"
    app.state.runner.cancel(res.json()["id"])


def test_public_reports_are_rate_limited_per_link(app_env):
    _settings, _app, admin, student, _other = app_env
    token = admin.post(f"/api/lectures/{LID}/shares").json()["token"]
    codes = [student.post(f"/api/public/{token}/report", json={"kind": "other"}).status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_signups_are_rate_limited(app_env, monkeypatch):
    from lecture_auto.web import account_routes

    _settings, _app, _admin, _student, other = app_env
    monkeypatch.setattr(account_routes, "SIGNUP_MAX", 2)
    codes = [other.post("/api/signup", json={"email": f"u{i}@example.com", "password": "password-1234",
                                             "display_name": "U", "terms_accepted": True}).status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_key_encrypted_under_an_old_secret_reads_as_unregistered(app_env):
    from lecture_auto.web.accounts import Accounts

    settings, app, _admin, _student, _other = app_env
    uid = app.state.accounts.list_users()[0].id
    app.state.accounts.save_key(uid, "baze_test_key_1234")
    rotated = Accounts(Settings(root=settings.root, password=settings.password, secret=b"t" * 32))
    assert rotated.api_key(uid) is None and rotated.key_last4(uid) is None


def test_subtitles_download_and_viewer_cache_is_not_listed(app_env):
    settings, _app, admin, _student, _other = app_env
    srt = admin.get(f"/api/lectures/{LID}/export/subtitles.srt")
    assert srt.status_code == 200 and "-->" in srt.text and SENTS[0][:8] in srt.text
    vtt = admin.get(f"/api/lectures/{LID}/export/subtitles.vtt")
    assert vtt.text.startswith("WEBVTT")
    assert (settings.output_dir / LID / f"{LID}.viewer.json").exists()
    names = [f["name"] for f in admin.get(f"/api/lectures/{LID}").json()["files"]]
    assert f"{LID}.mp4" in names and not any(n.endswith(".viewer.json") for n in names)
