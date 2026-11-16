import os
from datetime import UTC, datetime

import pytest

from lecture_auto.pipeline.approval import save_approvals
from lecture_auto.schemas.production import ApprovalManifest, ApprovedSlide
from lecture_auto.web.progress import job_progress
from lecture_auto.web.settings import Settings

START = 1_800_000_000.0


@pytest.fixture
def settings(tmp_path):
    return Settings(root=tmp_path, password="x", secret=b"a" * 32)


def _touch(path, mtime):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    os.utime(path, (mtime, mtime))


def _work(settings, slides):
    work = settings.work_dir / "01_x"
    for n in slides:
        _touch(work / "rendered" / f"slide_{n:03d}.png", START - 100)
    return work


def test_produce_counts_slides_finished_since_start_and_skips_approved(settings):
    work = _work(settings, [1, 2, 3, 4])
    save_approvals(work, ApprovalManifest(lecture_id="01_x", slides={4: ApprovedSlide(
        wav="slide_004.wav", sha256="0", approved_at=datetime.now(UTC), source="existing")}))
    claim = work / "audio" / ".claim"
    _touch(claim / "slide_001.done", START + 10)
    _touch(claim / "slide_002.done", START + 30)
    _touch(claim / "slide_003.done", START - 50)  # left by an earlier run
    _touch(claim / "slide_004.done", START + 5)  # approved: produce does not redo it
    job = {"kind": "produce", "status": "running", "lecture_id": "01_x", "started_at": START}
    assert job_progress(settings, job, now=START + 60) == {"done": 2, "total": 3, "eta_seconds": 30}


def test_regen_counts_only_requested_slides(settings):
    work = _work(settings, [1, 2, 3])
    _touch(work / "audio" / "slide_002.cand.wav.qc.json", START + 20)
    _touch(work / "audio" / "slide_003.wav.qc.json", START - 20)
    _touch(work / "audio" / "slide_001.wav.qc.json", START + 20)
    job = {"kind": "regen", "status": "running", "lecture_id": "01_x", "started_at": START, "slides": [2, 3]}
    assert job_progress(settings, job, now=START + 40) == {"done": 1, "total": 2, "eta_seconds": 40}


@pytest.mark.parametrize("job", [
    {"kind": "scripts", "status": "running", "started_at": START},
    {"kind": "produce", "status": "queued", "started_at": None},
    {"kind": "produce", "status": "succeeded", "started_at": START},
])
def test_no_progress_outside_running_voice_jobs(settings, job):
    _work(settings, [1])
    assert job_progress(settings, {**job, "lecture_id": "01_x"}, now=START + 5) is None


def test_job_route_reports_progress(settings):
    from fastapi.testclient import TestClient

    from lecture_auto.web.app import create_app

    with TestClient(create_app(settings)) as client:
        assert client.post("/api/login", json={"password": "x"}).status_code == 200
        runner = client.app.state.runner
        job = {"id": "j1", "kind": "produce", "status": "running", "lecture_id": "01_x",
               "started_at": START, "owner": None}
        runner._jobs["j1"] = job
        _work(settings, [1, 2])
        _touch(settings.work_dir / "01_x" / "audio" / ".claim" / "slide_001.done", START + 10)
        body = client.get("/api/jobs/j1").json()
    assert body["progress"]["done"] == 1 and body["progress"]["total"] == 2
