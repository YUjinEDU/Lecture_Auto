import json
import os
import shutil
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lecture_auto.core.jobs import command, read_spec
from lecture_auto.core.project import ProjectConfig, load_projects, save_project
from lecture_auto.pipeline.cache import cache_path_for, content_hash, write_cache_hash
from lecture_auto.production import batch as bgl
from lecture_auto.web.app import create_app
from lecture_auto.web.runner import JobRunner
from lecture_auto.web.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
LID = "90_웹테스트"
BUILTIN = "09_종합설계_06_Product_Backlog"
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
    save_project(ProjectConfig(
        id=LID, name="웹 테스트", subject="테스트", pdf="data/x.pdf",
        ref_voice="data/audio_ref/reference_v2.wav", web=True,
    ), settings.projects_dir)
    save_project(ProjectConfig(id=BUILTIN, name="기본", subject="종합설계", pdf="data/b.pdf"), settings.projects_dir)
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
    assert BUILTIN in lectures
    mine = lectures[LID]
    assert mine["web"] is True
    assert mine["video_state"] == "draft"
    assert mine["held_back"] == [2]
    assert mine["no_audio"] == [3]
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
    lec = client.get(f"/api/lectures/{LID}").json()
    assert lec["held_back"] == [1, 2]
    assert lec["no_audio"] == [3]


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
    [entry] = [p for p in load_projects(settings.projects_dir) if p.id == new_id]
    assert entry.pdf == Path(f"data/web/uploads/{new_id}/{new_id}.pdf")
    assert entry.ref_voice == Path("data/audio_ref/reference_v2.wav") and entry.master_audio and entry.web
    assert entry.target_minutes == 25 and entry.min_minutes is None
    assert (settings.root / entry.pdf).read_bytes() == b"%PDF-1.4 test"
    assert client.delete(f"/api/lectures/{BUILTIN}").status_code == 400
    assert client.delete(f"/api/lectures/{new_id}").status_code == 200
    assert new_id not in {p.id for p in load_projects(settings.projects_dir)}


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
    save_project(ProjectConfig(id="92_다른강의", name="b", subject="s", pdf="data/y.pdf", web=True), settings.projects_dir)
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
        assert "fake-args: -m lecture_auto.core.worker " in log
        spec = read_spec(settings.jobs_dir / "specs" / f"{first['id']}.json")
        assert command(spec) == ("batch", ["--only", LID, "--assemble-only"])
        assert first["env"]["LECTURE_AUTO_PROJECTS"] == str(settings.projects_dir)
        assert "LECTURE_AUTO_REF_VOICE" not in first["env"] and "LECTURE_AUTO_MASTER_AUDIO" not in first["env"]
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
        assert "-m lecture_auto.core.worker" in runner.read_log(job["id"], 0)[0]
        target, args = command(read_spec(s.jobs_dir / "specs" / f"{job['id']}.json"))
        assert target == "produce" and args[2:] == ["--gpus", "0", "--fix-failed", "--heal"]
        assert done["outcome"] == {"video_state": "draft", "held_back": 1, "no_audio": 1, "scripts": 3,
                                   "audio": 2, "candidates": 1}
        assert runner.get(job["id"])["outcome"] == done["outcome"]


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


def test_reuploading_a_deleted_title_does_not_inherit_its_files(client, sandbox):
    settings, _ = sandbox
    deck = {"file": ("deck.pdf", b"%PDF-1.4 test")}
    first = client.post("/api/lectures", data={"name": "요구사항 분석"}, files=deck).json()["id"]
    (settings.work_dir / first / "scripts").mkdir(parents=True)
    (settings.output_dir / first).mkdir(parents=True)
    (settings.output_dir / first / f"{first}.mp4").write_bytes(b"old final")
    assert client.delete(f"/api/lectures/{first}").status_code == 200
    again = client.post("/api/lectures", data={"name": "요구사항 분석"}, files=deck).json()
    assert again["id"] != first
    assert again["video_state"] == "none"


def test_delete_is_refused_only_for_the_busy_lecture(sandbox):
    settings, fake = sandbox
    s = Settings(root=settings.root, password=PASSWORD, secret=b"s" * 32, python=str(fake),
                 extra_env={"FAKE_SLEEP": "30"})
    runner = JobRunner(s)
    c = TestClient(create_app(s, runner))
    with c:
        c.post("/api/login", json={"password": PASSWORD})
        deck = {"file": ("d.pdf", b"%PDF-1.4")}
        busy = c.post("/api/lectures", data={"name": "작업 중 강의"}, files=deck).json()["id"]
        other = c.post("/api/lectures", data={"name": "다른 강의"}, files=deck).json()["id"]
        job = c.post(f"/api/lectures/{busy}/jobs", json={"kind": "produce"}).json()
        assert c.delete(f"/api/lectures/{busy}").status_code == 409
        assert c.delete(f"/api/lectures/{other}").status_code == 200
        c.post(f"/api/jobs/{job['id']}/cancel")
        runner.wait(job["id"], ("cancelled", "succeeded", "failed"), timeout=20)
        assert c.delete(f"/api/lectures/{busy}").status_code == 200


def test_a_job_that_raises_fails_and_the_queue_keeps_going(sandbox, monkeypatch):
    settings, fake = sandbox
    s = Settings(root=settings.root, password=PASSWORD, secret=b"s" * 32, python=str(fake))
    runner = JobRunner(s)
    real_log_path = runner.log_path
    broken = set()

    def log_path(job_id):
        if job_id in broken:
            raise OSError("disk full")
        return real_log_path(job_id)

    monkeypatch.setattr(runner, "log_path", log_path)
    first = runner.submit("assemble", {"id": LID})
    broken.add(first["id"])
    second = runner.submit("check", {"id": "92_다른강의"})
    runner.start()
    try:
        assert runner.wait(first["id"], ("succeeded", "failed"), timeout=10)["status"] == "failed"
        assert runner.wait(second["id"], ("succeeded", "failed"), timeout=10)["status"] == "succeeded"
    finally:
        runner.stop()


def test_log_reads_never_split_a_utf8_character(sandbox):
    settings, _ = sandbox
    runner = JobRunner(settings)
    body = "가" * 100_000
    runner.log_path("x").write_bytes(body.encode())
    text, offset, out = "", 0, []
    while True:
        text, nxt = runner.read_log("x", offset, limit=1000)
        if nxt == offset:
            break
        out.append(text)
        offset = nxt
    assert "\ufffd" not in "".join(out)
    assert "".join(out) == body


def test_a_negative_log_offset_reads_the_tail(sandbox):
    settings, _ = sandbox
    runner = JobRunner(settings)
    runner.log_path("x").write_bytes(b"start\n" + b"x" * 5000 + b"\nTraceback: boom\n")
    text, offset = runner.read_log("x", -16)
    assert text == "Traceback: boom\n"
    assert offset == runner.log_path("x").stat().st_size


def test_wrong_passwords_are_capped_across_clients(sandbox, monkeypatch):
    import lecture_auto.web.app as web_app

    monkeypatch.setattr(web_app, "LOGIN_FAILURE_DELAY", 0)
    settings, _ = sandbox
    c = _client(settings)
    for _ in range(web_app.LOGIN_FAILURES_MAX):
        assert c.post("/api/login", json={"password": "wrong"}).status_code == 401
    # Past the cap even the right password is refused, so guessing cannot continue.
    assert c.post("/api/login", json={"password": PASSWORD}).status_code == 429
    c.__exit__(None, None, None)


def test_anonymous_requests_are_refused_before_the_body_is_read(sandbox):
    settings, _ = sandbox
    c = _client(settings)
    # A body FastAPI cannot parse would answer 400 if the upload were parsed before auth.
    r = c.post("/api/lectures", content=b"not multipart", headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 401
    big = c.post("/api/login", content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/json"})
    assert big.status_code == 413
    c.__exit__(None, None, None)


def test_session_cookie_is_secure_only_behind_https(sandbox):
    settings, _ = sandbox
    c = _client(settings)
    plain = c.post("/api/login", json={"password": PASSWORD})
    assert "secure" not in plain.headers["set-cookie"].lower()
    c.cookies.clear()
    https = c.post("/api/login", json={"password": PASSWORD}, headers={"x-forwarded-proto": "https"})
    assert "secure" in https.headers["set-cookie"].lower()
    c.__exit__(None, None, None)


def test_a_recycled_pid_is_not_adopted_and_cancel_never_signals_it(sandbox):
    from lecture_auto.web.runner import _proc_identity

    settings, _ = sandbox
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    me = os.getpid()
    base = {"kind": "produce", "label": "x", "lecture_id": LID, "status": "running", "created_at": 1.0, "pid": me}
    for name, ident in (("recycled", "boot:0"), ("ours", _proc_identity(me))):
        job = {**base, "id": name, "pid_id": ident}
        (settings.jobs_dir / f"{name}.json").write_text(json.dumps(job), encoding="utf-8")
    runner = JobRunner(settings)
    # The same pid answers kill(0) for both, but only the one whose start tick matches is ours.
    assert runner.get("recycled")["status"] == "interrupted"
    assert runner.get("ours")["status"] == "running"
    # The pid is recycled between adoption and a cancel: nothing may be signalled (a killpg
    # on this test process's own group would take the test run down with it).
    runner._jobs["ours"]["pid_id"] = "boot:0"
    assert runner.cancel("ours")["status"] == "interrupted"
