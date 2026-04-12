from fastapi.testclient import TestClient
from lecture_auto.api.main import app
from lecture_auto.demo.state import create_job, upsert_slide, get_job


client = TestClient(app)


def test_slide_tts_status_defaults_to_pending():
    create_job("test-001", "test.pdf", "Test", 8)
    upsert_slide("test-001", 1, {"script": "Hello world"})
    job = get_job("test-001")
    slide = next(s for s in job["slides"] if s["slide_number"] == 1)
    assert slide.get("tts_status") == "pending"


def test_upsert_slide_preserves_existing_fields():
    create_job("test-002", "test.pdf", "Test", 8)
    upsert_slide("test-002", 1, {"script": "Hello", "tts_status": "done"})
    upsert_slide("test-002", 1, {"script": "Updated"})
    job = get_job("test-002")
    slide = next(s for s in job["slides"] if s["slide_number"] == 1)
    assert slide["tts_status"] == "done"   # preserved
    assert slide["script"] == "Updated"    # updated


def test_approve_endpoint_returns_ok(monkeypatch):
    create_job("job-approve-01", "test.pdf", "Test", 8)
    upsert_slide("job-approve-01", 1, {"script": "Hello"})

    monkeypatch.setattr("lecture_auto.api.routes.demo.rerun_tts_only", lambda *a, **k: None)

    resp = client.post("/demo/api/jobs/job-approve-01/slides/1/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["slide"] == 1
    assert body["tts"] == "queued"


def test_approve_sets_slide_tts_status_to_queued(monkeypatch):
    create_job("job-approve-02", "test.pdf", "Test", 8)
    upsert_slide("job-approve-02", 1, {"script": "Hello"})

    monkeypatch.setattr("lecture_auto.api.routes.demo.rerun_tts_only", lambda *a, **k: None)

    client.post("/demo/api/jobs/job-approve-02/slides/1/approve")
    job = get_job("job-approve-02")
    slide = next(s for s in job["slides"] if s["slide_number"] == 1)
    assert slide["tts_status"] == "queued"
    assert slide.get("approved") is True
