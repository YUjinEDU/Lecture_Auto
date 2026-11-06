import json
from dataclasses import replace

from conftest import PASSWORD, deck, signup
from fastapi.testclient import TestClient

from lecture_auto.core.project import ProjectConfig, save_project
from lecture_auto.web.accounts import Accounts, Registration
from lecture_auto.web.app import create_app
from lecture_auto.web.runner import JobRunner


def test_all_lecture_and_job_resources_are_private(client, settings, stopped_runner):
    first = signup(client)
    lecture = deck(client)
    accounts = Accounts(settings)
    accounts.save_key(first["id"], "fake-owner-key-1234")
    lid = lecture["id"]
    for directory, filename in [("audio", "slide_001.wav"), ("rendered", "slide_001.png")]:
        path = settings.work_dir / lid / directory / filename
        path.parent.mkdir(parents=True)
        path.write_bytes(b"private")
    out = settings.output_dir / lid / "video.mp4"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"private")
    job = stopped_runner.submit("scripts", {"id": lid, "owner": first["id"]})
    with TestClient(create_app(settings, stopped_runner)) as other:
        signup(other, "other@example.com")
        assert other.get("/api/lectures").json() == []
        assert other.get("/api/jobs").json() == []
        assert other.get("/api/settings/key").json() == {"last4": None}
        paths = [
            ("GET", f"/api/lectures/{lid}"),
            ("GET", f"/api/lectures/{lid}/slides/1/image"),
            ("GET", f"/api/lectures/{lid}/slides/1/audio/main"),
            ("GET", f"/api/lectures/{lid}/files/video.mp4"),
            ("POST", f"/api/lectures/{lid}/jobs"),
            ("PUT", f"/api/lectures/{lid}/slides/1/script"),
            ("DELETE", f"/api/lectures/{lid}"),
            ("GET", f"/api/jobs/{job['id']}"),
            ("GET", f"/api/jobs/{job['id']}/log"),
            ("POST", f"/api/jobs/{job['id']}/cancel"),
        ]
        for method, path in paths:
            assert other.request(method, path).status_code == 404, path
    assert lecture["owner"] == first["id"]


def test_ownerless_lectures_are_admin_only(client, settings):
    save_project(ProjectConfig(id="99_legacy", name="legacy", subject="s"), settings.projects_dir)
    signup(client)
    assert client.get("/api/lectures/99_legacy").status_code == 404
    client.post("/api/login", json={"password": PASSWORD})
    assert client.get("/api/lectures/99_legacy").status_code == 200


def test_queue_refuses_non_admin_without_key(client):
    signup(client)
    lid = deck(client)["id"]
    result = client.post(f"/api/lectures/{lid}/jobs", json={"kind": "scripts"})
    assert result.status_code == 400
    assert "API" in result.json()["detail"]


def test_owner_key_reaches_process_but_never_artifacts(settings, tmp_path):
    fake = tmp_path / "fake-worker"
    receipt = tmp_path / "receipt.json"
    fake.write_text("#!/bin/sh\nprintf '%s\\n%s' \"$BAZE_API_KEY\" \"$FACTCHAT_BASE_URL\" > \"$RECEIPT\"\n"
                    "printf '%s\\n' \"$FACTCHAT_API_KEY\"\n")
    fake.chmod(0o700)
    settings = replace(settings, python=str(fake), extra_env={
        "RECEIPT": str(receipt), "FACTCHAT_BASE_URL": "https://wrong.invalid",
        "FACTCHAT_API_KEY": "wrong-fake-server-key"})
    accounts = Accounts(settings)
    user = accounts.signup(Registration(email="user@example.com", password=PASSWORD,
                                        display_name="name", terms_accepted=True))
    key = "fake-distinct-owner-secret-9876"
    accounts.save_key(user.id, key)
    save_project(ProjectConfig(id="01_x", name="x", subject="s", owner=user.id), settings.projects_dir)
    runner = JobRunner(settings)
    job = runner.submit("scripts", {"id": "01_x", "owner": user.id})
    runner.start()
    try:
        assert runner.wait(job["id"], ("succeeded", "failed"), 10)["status"] == "succeeded"
    finally:
        runner.stop()
    assert receipt.read_text() == key + "\nhttps://factchat-cloud.mindlogic.ai/v1/gateway"
    for path in settings.jobs_dir.rglob("*"):
        if path.is_file():
            assert key.encode() not in path.read_bytes(), path
    assert "[REDACTED]" in runner.read_log(job["id"], 0)[0]
    assert key not in json.dumps(job)


def test_lecture_and_storage_quota_keep_rejected_uploads_off_disk(settings):
    settings = replace(settings, max_lectures=1, storage_limit_mb=1)
    with TestClient(create_app(settings)) as client:
        signup(client)
        lid = deck(client)["id"]
        assert client.post("/api/lectures", data={"name": "another"},
                           files={"file": ("a.pdf", b"%PDF-test")}).status_code == 409
        client.delete(f"/api/lectures/{lid}")
        # Deleted lectures retain uploads and must continue counting against storage.
        path = next(settings.uploads_dir.rglob("*.pdf"))
        path.write_bytes(b"x" * 1024 * 1024)
        assert client.post("/api/lectures", data={"name": "another"},
                           files={"file": ("a.pdf", b"%PDF-test")}).status_code == 413


def test_admin_disables_lecture_and_new_jobs(client, settings):
    signup(client)
    lid = deck(client)["id"]
    with TestClient(create_app(settings)) as admin:
        admin.post("/api/login", json={"password": PASSWORD})
        assert admin.put(f"/api/admin/lectures/{lid}", json={"disabled": True}).status_code == 200
        assert admin.post(f"/api/lectures/{lid}/jobs", json={"kind": "scripts"}).status_code == 400
    assert client.get(f"/api/lectures/{lid}").status_code == 404
    assert client.get("/api/lectures").json() == []
