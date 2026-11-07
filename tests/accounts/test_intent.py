from datetime import UTC, datetime

import pytest
from conftest import deck, signup
from fastapi.testclient import TestClient

from lecture_auto.core.jobs import command, read_spec
from lecture_auto.production.intent import load_intent, save_intent
from lecture_auto.schemas.intent import IntentSheet, SlideIntent
from lecture_auto.web.accounts import Accounts
from lecture_auto.web.app import create_app
from lecture_auto.web.job_process import GPU_KINDS, KINDS


@pytest.fixture
def intent_env(settings, stopped_runner):
    app = create_app(settings, stopped_runner)
    with TestClient(app) as client:
        user = signup(client)
        Accounts(settings).save_key(user["id"], "fake-owner-key-1234")
        lecture = deck(client)
        work = settings.work_dir / lecture["id"]
        (work / "rendered").mkdir(parents=True)
        for n in (1, 2):
            (work / "rendered" / f"slide_{n:03d}.png").write_bytes(b"png")
        sheet = IntentSheet(
            lecture_id=lecture["id"], generated_at=datetime.now(UTC), input_hash="inputs",
            slides=[SlideIntent(slide=n, thesis=f"핵심 {n}", role="개념", importance=2,
                                seconds=60, pitfall="", example="") for n in (1, 2)],
        )
        yield client, work, sheet, stopped_runner


def test_get_put_round_trip_preserves_provenance_and_marks_edited(intent_env):
    client, work, sheet, _ = intent_env
    url = f"/api/lectures/{sheet.lecture_id}/intent"
    assert client.get(url).status_code == 404
    save_intent(work, sheet)
    body = client.get(url).json()
    body["slides"][0].update(thesis="교수자가 정한 핵심", seconds=95, role="예시")
    body["input_hash"] = "client cannot change provenance"
    response = client.put(url, json=body)
    assert response.status_code == 200
    stored = load_intent(work)
    assert stored.edited and stored.input_hash == "inputs"
    assert stored.slides[0].thesis == "교수자가 정한 핵심"
    assert stored.slides[0].seconds == 95 and stored.slides[0].role == "예시"


@pytest.mark.parametrize("invalid", ["coverage", "range", "lecture_id", "duplicate"])
def test_put_rejects_incomplete_or_invalid_sheet_without_writing(intent_env, invalid):
    client, work, sheet, _ = intent_env
    save_intent(work, sheet)
    body = sheet.model_dump(mode="json")
    match invalid:
        case "coverage":
            body["slides"] = body["slides"][:1]
        case "range":
            body["slides"][0]["seconds"] = 601
        case "lecture_id":
            body["lecture_id"] = "other"
        case "duplicate":
            body["slides"][1] = body["slides"][0]
    assert client.put(f"/api/lectures/{sheet.lecture_id}/intent", json=body).status_code == 422
    assert load_intent(work) == sheet


def test_other_user_get_and_put_are_404(intent_env):
    client, work, sheet, _ = intent_env
    save_intent(work, sheet)
    signup(client, "other@example.com")
    url = f"/api/lectures/{sheet.lecture_id}/intent"
    assert client.get(url).status_code == 404
    assert client.put(url, json=sheet.model_dump(mode="json")).status_code == 404


def test_edited_draft_requires_force_and_worker_receives_confirmation(intent_env, monkeypatch):
    client, work, sheet, runner = intent_env
    # Keep the real queue and spec writer, without launching an external process.
    monkeypatch.setattr(runner, "_next", lambda: None)
    save_intent(work, sheet.model_copy(update={"edited": True}))
    url = f"/api/lectures/{sheet.lecture_id}/jobs"
    assert client.post(url, json={"kind": "intent"}).status_code == 409
    result = client.post(url, json={"kind": "intent", "force": True})
    assert result.status_code == 200
    job = result.json()
    spec = read_spec(runner.settings.jobs_dir / "specs" / f"{job['id']}.json")
    assert command(spec) == ("batch", ["--only", sheet.lecture_id, "--intent", "--force-intent"])
    assert job["label"] == KINDS["intent"] == "슬라이드 의도 정리"
    assert spec.kind not in GPU_KINDS
    body = sheet.model_dump(mode="json")
    assert client.put(f"/api/lectures/{sheet.lecture_id}/intent", json=body).status_code == 409


def test_job_spec_intent_without_force_preserves_cpu_only_command():
    from lecture_auto.core.jobs import JobSpec
    assert command(JobSpec(kind="intent", project_id="x")) == ("batch", ["--only", "x", "--intent"])
