import json
import os
import shutil
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import scripts.batch_generate_lectures as bgl
from lecture_auto.pipeline.cache import cache_path_for, content_hash, write_cache_hash
from lecture_auto.web.app import create_app
from lecture_auto.web.registry import save_web_lectures
from lecture_auto.web.runner import JobRunner
from lecture_auto.web.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
LID = "90_웹테스트"
PASSWORD = "pw-test"
FAKE_PY = """#!/bin/sh
echo "fake-args: $*"
sleep "${FAKE_SLEEP:-0}"
exit "${FAKE_EXIT:-0}"
"""


def _script(work: Path, n: int, text: str, own_hash: bool = True) -> Path:
    path = work / "scripts" / f"script_{n:03d}.json"
    body = json.dumps({"slide_number": n, "target_seconds": 10.0, "script": text}, ensure_ascii=False, indent=2)
    path.write_text(body, encoding="utf-8")
    if own_hash:
        write_cache_hash(path, content_hash(body))
    return path


def _wav(audio: Path, name: str, ok: bool, script: str | None = None, ref: bytes = b"") -> None:
    wav = audio / name
    wav.write_bytes(b"RIFF" + os.urandom(64))
    qc = {"ok": ok, "gate_reasons": [] if ok else ["long"], "stt": {"status": "pass" if ok else "mismatch", "cer": 0.02},
          "segments": [{"index": 0, "text": "문장", "fallback": not ok, "stt_status": "pass" if ok else "mismatch"}]}
    wav.with_name(wav.name + ".qc.json").write_text(json.dumps(qc), encoding="utf-8")
    if script is not None:
        write_cache_hash(wav, bgl._tts_cache_key(script, ref, 10.0))


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "root"
    work = root / "data" / "work_batch" / LID
    for d in ("rendered", "scripts", "audio"):
        (work / d).mkdir(parents=True)
    shutil.copytree(ROOT / "config", root / "config")
    ref = root / "data" / "audio_ref" / "reference_v2.wav"
    ref.parent.mkdir(parents=True)
    ref.write_bytes(b"ref-voice")
    for n in (1, 2, 3):
        (work / "rendered" / f"slide_{n:03d}.png").write_bytes(b"\x89PNG fake")
    _script(work, 1, "첫 번째 슬라이드입니다.")
    _script(work, 2, "두 번째 슬라이드입니다.")
    _script(work, 3, "세 번째 슬라이드입니다.", own_hash=False)
    audio = work / "audio"
    _wav(audio, "slide_001.wav", True, "첫 번째 슬라이드입니다.", b"ref-voice")
    _wav(audio, "slide_002.wav", False)
    _wav(audio, "slide_002.cand.wav", True)
    (audio / "slide_002.cand.wav.json").write_text(json.dumps({"ok": True, "cache_key": "k"}), encoding="utf-8")
    out = root / "output" / LID
    out.mkdir(parents=True)
    (out / f"{LID}_DRAFT.mp4").write_bytes(b"mp4")
    (out / "secret.txt").write_text("not served")
    fake = tmp_path / "fakepy"
    fake.write_text(FAKE_PY)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    settings = Settings(root=root, password=PASSWORD, secret=b"s" * 32)
    save_web_lectures([{
        "id": LID, "name": "웹 테스트", "subject": "테스트", "pdf": "data/x.pdf",
        "ref_voice": "data/audio_ref/reference_v2.wav",
    }], settings.registry)
    return settings, fake


def _client(settings: Settings) -> TestClient:
    client = TestClient(create_app(settings))
    client.__enter__()
    return client


@pytest.fixture
def client(sandbox):
    settings, _ = sandbox
    c = _client(settings)
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 200
    yield c
    c.__exit__(None, None, None)


def test_api_requires_login(sandbox):
    settings, _ = sandbox
    c = _client(settings)
    assert c.get("/api/lectures").status_code == 401
    assert c.get(f"/api/lectures/{LID}/slides/1/image").status_code == 401
    assert c.post("/api/login", json={"password": "wrong"}).status_code == 401
    c.cookies.set("la_session", "9999999999.forged")
    assert c.get("/api/lectures").status_code == 401
    c.__exit__(None, None, None)


def test_dashboard_and_slide_states(client):
    lectures = {lec["id"]: lec for lec in client.get("/api/lectures").json()}
    assert "09_종합설계_06_Product_Backlog" in lectures
    mine = lectures[LID]
    assert mine["web"] is True
    assert mine["video_state"] == "draft"
    assert mine["held_back"] == [2, 3]
    views = {v["number"]: v for v in client.get(f"/api/lectures/{LID}").json()["slide_list"]}
    assert views[1]["state"] == "pass"
    assert views[2]["state"] == "held" and views[2]["candidate"] is True
    assert views[2]["qc"]["failing_segments"][0]["text"] == "문장"
    assert views[2]["candidate_qc"]["ok"] is True and views[2]["candidate_ok"] is True
    assert views[3]["state"] == "no_audio"


def test_script_edit_is_kept_as_hand_edit(client, sandbox):
    settings, _ = sandbox
    scripts = settings.work_dir / LID / "scripts"
    for n in (1, 3):
        r = client.put(f"/api/lectures/{LID}/slides/{n}/script", json={"script": "고친 대본입니다."})
        assert r.status_code == 200, r.text
        assert r.json()["hand_edited"] is True
        assert json.loads((scripts / f"script_{n:03d}.json").read_text(encoding="utf-8"))["script"] == "고친 대본입니다."
        assert bgl._hand_edited(scripts / f"script_{n:03d}.json") is not None
    assert cache_path_for(scripts / "script_003.json").exists()
    assert client.get(f"/api/lectures/{LID}").json()["held_back"] == [1, 2, 3]


def test_approve_and_promote_go_through_the_cli(client, sandbox):
    settings, _ = sandbox
    audio = settings.work_dir / LID / "audio"
    cand_bytes = (audio / "slide_002.cand.wav").read_bytes()
    r = client.post(f"/api/lectures/{LID}/slides/2/promote", json={})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "approved"
    assert (audio / "slide_002.wav").read_bytes() == cand_bytes
    r = client.post(f"/api/lectures/{LID}/slides/1/approve")
    assert r.status_code == 200, r.text
    approved = json.loads((settings.work_dir / LID / "approved.json").read_text(encoding="utf-8"))
    assert set(approved["slides"]) == {"1", "2"}
    assert client.post(f"/api/lectures/{LID}/slides/3/approve").status_code == 404


def test_upload_validation_and_registration(client, sandbox):
    settings, _ = sandbox
    bad_ext = client.post("/api/lectures", data={"name": "x"}, files={"file": ("a.txt", b"hello")})
    assert bad_ext.status_code == 400
    bad_magic = client.post("/api/lectures", data={"name": "x"}, files={"file": ("a.pdf", b"PK\x03\x04zip")})
    assert bad_magic.status_code == 400
    ok = client.post(
        "/api/lectures", data={"name": "08 새 강의", "subject": "종합설계", "target_minutes": "25"},
        files={"file": ("deck.pdf", b"%PDF-1.4 test")},
    )
    assert ok.status_code == 200, ok.text
    new_id = ok.json()["id"]
    assert new_id == "91_08_새_강의"
    entry = json.loads(settings.registry.read_text(encoding="utf-8"))[-1]
    assert entry["pdf"] == f"data/web/uploads/{new_id}/{new_id}.pdf"
    assert entry["ref_voice"] == "data/audio_ref/reference_v2.wav" and entry["master_audio"] is True
    assert (settings.root / entry["pdf"]).read_bytes() == b"%PDF-1.4 test"
    assert client.delete("/api/lectures/09_종합설계_06_Product_Backlog").status_code == 400
    assert client.delete(f"/api/lectures/{new_id}").status_code == 200


def test_file_endpoints_reject_traversal_and_unknowns(client):
    assert client.get(f"/api/lectures/{LID}/files/{LID}_DRAFT.mp4").status_code == 200
    assert client.get(f"/api/lectures/{LID}/files/secret.txt").status_code == 404
    assert client.get(f"/api/lectures/{LID}/files/..%2F..%2Fconfig%2Fpronunciation.yaml").status_code == 404
    assert client.get(f"/api/lectures/{LID}/slides/1/audio/..%2Fx").status_code in (400, 404)
    assert client.get(f"/api/lectures/{LID}/slides/1/audio/main").status_code == 200
    assert client.get("/api/lectures/..%2F..%2Fetc/slides/1/image").status_code == 404
    assert client.get("/api/lectures/nope").status_code == 404


def test_job_runs_queues_conflicts_and_cancels(sandbox):
    settings, fake = sandbox
    second = {"id": "92_다른강의", "name": "b", "subject": "s", "pdf": "data/y.pdf"}
    save_web_lectures(json.loads(settings.registry.read_text(encoding="utf-8")) + [second], settings.registry)
    settings = Settings(root=settings.root, password=PASSWORD, secret=b"s" * 32, python=str(fake),
                        extra_env={"FAKE_SLEEP": "30"})
    runner = JobRunner(settings)
    c = TestClient(create_app(settings, runner))
    with c:
        c.post("/api/login", json={"password": PASSWORD})
        first = c.post(f"/api/lectures/{LID}/jobs", json={"kind": "assemble"}).json()
        with runner._lock:
            assert runner._lock.wait_for(lambda: runner._jobs[first["id"]]["pid"], timeout=10)
        running = runner.get(first["id"])
        assert running["status"] == "running"
        assert c.post(f"/api/lectures/{LID}/jobs", json={"kind": "scripts"}).status_code == 409
        assert c.put(f"/api/lectures/{LID}/slides/1/script", json={"script": "x"}).status_code == 409
        queued = c.post("/api/lectures/92_다른강의/jobs", json={"kind": "check"}).json()
        assert runner.get(queued["id"])["status"] == "queued"
        assert c.post("/api/lectures/92_다른강의/jobs", json={"kind": "regen"}).status_code == 400
        assert c.post("/api/lectures/92_다른강의/jobs", json={"kind": "nope"}).status_code == 400
        c.post(f"/api/jobs/{first['id']}/cancel")
        done = runner.wait(first["id"], ("cancelled", "succeeded", "failed"), timeout=10)
        assert done["status"] == "cancelled"
        with pytest.raises(ProcessLookupError):
            os.killpg(running["pid"], 0)
        c.post(f"/api/jobs/{queued['id']}/cancel")
        runner.wait(queued["id"], ("cancelled", "succeeded", "failed"), timeout=10)
        log = c.get(f"/api/jobs/{first['id']}/log").json()["text"]
        assert f"fake-args: -m scripts.batch_generate_lectures --only {LID} --assemble-only" in log
        assert first["env"]["LECTURE_AUTO_REF_VOICE"] == "data/audio_ref/reference_v2.wav"
        assert first["env"]["CUDA_VISIBLE_DEVICES"] == "0"


def test_job_success_and_failure_exit_codes(sandbox):
    settings, fake = sandbox
    for exit_code, status in (("0", "succeeded"), ("1", "failed")):
        s = Settings(root=settings.root, password=PASSWORD, secret=b"s" * 32, python=str(fake),
                     extra_env={"FAKE_EXIT": exit_code})
        runner = JobRunner(s)
        runner.start()
        job = runner.submit("produce", {"id": LID})
        done = runner.wait(job["id"], ("succeeded", "failed"), timeout=10)
        runner.stop()
        assert done["status"] == status
        assert "--gpus 0 --fix-failed --heal" in runner.read_log(job["id"], 0)[0]


def test_restart_marks_dead_running_job_interrupted(sandbox):
    settings, _ = sandbox
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    stale = {"id": "old", "kind": "produce", "label": "x", "lecture_id": LID, "status": "running",
             "pid": 2 ** 22 + 7, "created_at": 1.0}
    (settings.jobs_dir / "old.json").write_text(json.dumps(stale), encoding="utf-8")
    assert JobRunner(settings).get("old")["status"] == "interrupted"


def test_cancel_while_the_runner_is_starting_the_job_still_cancels(sandbox, monkeypatch):
    import threading

    import lecture_auto.web.runner as runner_mod

    settings, fake = sandbox
    s = Settings(root=settings.root, password=PASSWORD, secret=b"s" * 32, python=str(fake),
                 extra_env={"FAKE_SLEEP": "30"})
    picked, release, spawned = threading.Event(), threading.Event(), threading.Event()
    real_popen = runner_mod.subprocess.Popen

    started = []

    def slow_popen(*args, **kwargs):
        picked.set()
        release.wait(10)
        started.append(real_popen(*args, **kwargs))
        spawned.set()
        return started[-1]

    monkeypatch.setattr(runner_mod.subprocess, "Popen", slow_popen)
    runner = JobRunner(s)
    runner.start()
    job = runner.submit("assemble", {"id": LID})
    assert picked.wait(10)
    runner.cancel(job["id"])
    release.set()
    if spawned.wait(5):
        try:
            assert started[0].wait(timeout=8) != 0
        finally:
            if started[0].poll() is None:
                os.killpg(started[0].pid, 9)
    final = runner.wait(job["id"], ("cancelled", "succeeded", "failed"), timeout=20)
    runner.stop()
    assert final["status"] == "cancelled"


def test_unapprove_and_restore_previous_through_the_cli(client, sandbox):
    settings, _ = sandbox
    audio = settings.work_dir / LID / "audio"
    old = (audio / "slide_002.wav").read_bytes()
    assert client.post(f"/api/lectures/{LID}/slides/2/restore-prev").status_code == 404
    assert client.post(f"/api/lectures/{LID}/slides/2/unapprove").status_code == 404
    assert client.post(f"/api/lectures/{LID}/slides/2/promote", json={}).json()["state"] == "approved"
    view = client.post(f"/api/lectures/{LID}/slides/2/unapprove").json()
    assert view["state"] == "held" and view["approval"] is None
    client.post(f"/api/lectures/{LID}/slides/2/approve")
    view = client.post(f"/api/lectures/{LID}/slides/2/restore-prev").json()
    assert (audio / "slide_002.wav").read_bytes() == old
    assert view["approval"] is None and view["previous"] is True
    assert client.get(f"/api/lectures/{LID}/slides/2/audio/prev").status_code == 200
