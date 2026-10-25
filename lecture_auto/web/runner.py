"""Serial job queue: one batch/produce subprocess at a time (one GPU), state on disk.

A job's JSON record and log live in ``data/web/jobs/``. The child runs in its own
session so a cancel can kill the whole process tree (produce.py starts workers).
On restart a still-alive child is adopted by pid rather than killed: a lost web
server must never throw away hours of GPU work.
"""
from __future__ import annotations

import codecs
import contextlib
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path

from lecture_auto.web.settings import DEFAULT_REF_VOICE, Settings

BATCH = ["-m", "scripts.batch_generate_lectures"]
PRODUCE = ["-m", "scripts.produce"]
KINDS = {
    "scripts": "대본 생성",
    "produce": "음성·영상 제작",
    "regen": "슬라이드 다시 만들기",
    "heal": "보류 슬라이드 자동 복구",
    "assemble": "영상 다시 조립",
    "check": "발음 점검",
}
GPU_KINDS = {"produce", "regen", "heal"}
ACTIVE = ("queued", "running")
KILL_GRACE_SECONDS = 15


class JobError(ValueError):
    pass


def job_env(settings: Settings, item: dict) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("LECTURE_AUTO_MASTER_AUDIO", "LECTURE_AUTO_REF_VOICE")}
    env.update({
        "PYTHONPATH": str(settings.code_root),
        "PYTHONUNBUFFERED": "1",
        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
        "CUDA_VISIBLE_DEVICES": settings.gpu,
        "LECTURE_AUTO_WEB_REGISTRY": str(settings.registry),
        "LECTURE_AUTO_REF_VOICE": str(item.get("ref_voice") or DEFAULT_REF_VOICE),
    })
    if item.get("master_audio"):
        env["LECTURE_AUTO_MASTER_AUDIO"] = "1"
    env.update(settings.extra_env)
    return env


def _slides_arg(slides: list[int] | None) -> str:
    if not slides or any(not isinstance(n, int) or n < 1 for n in slides):
        raise JobError("다시 만들 슬라이드 번호를 지정하세요")
    return ",".join(str(n) for n in sorted(set(slides)))


def job_argv(settings: Settings, kind: str, lecture_id: str, slides: list[int] | None = None) -> list[str]:
    only = ["--only", lecture_id]
    if kind == "scripts":
        args = BATCH + only + ["--skip-tts"]
    elif kind == "produce":
        workers = [] if settings.gpu == "0" else ["--workers-per-gpu", "1"]
        args = PRODUCE + only + ["--gpus", "0", "--fix-failed", "--heal"] + workers
    elif kind == "regen":
        args = BATCH + only + ["--slides", _slides_arg(slides), "--gpu", "0"]
    elif kind == "heal":
        args = BATCH + only + ["--heal", "--gpu", "0"]
    elif kind == "assemble":
        args = BATCH + only + ["--assemble-only"]
    elif kind == "check":
        args = BATCH + only + ["--check"]
    else:
        raise JobError(f"알 수 없는 작업 종류: {kind}")
    return [settings.python] + args


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class JobRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dir = settings.jobs_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Condition()
        self._jobs: dict[str, dict] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._items: dict[str, dict] = {}
        self._stop = False
        for path in sorted(self.dir.glob("*.json")):
            job = json.loads(path.read_text(encoding="utf-8"))
            self._jobs[job["id"]] = job
        with self._lock:
            for job in self._jobs.values():
                if job["status"] == "running" and not _pid_alive(job.get("pid")):
                    self._finish(job, "interrupted", None)
        self._thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop = True
            self._lock.notify_all()

    def _save(self, job: dict) -> None:
        tmp = self.dir / f"{job['id']}.json.tmp"
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.dir / f"{job['id']}.json")

    def log_path(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.log"

    def _finish(self, job: dict, status: str, code: int | None, outcome: dict | None = None) -> None:
        job.update(status=status, exit_code=code, finished_at=time.time(), outcome=outcome)
        self._save(job)
        self._lock.notify_all()

    def _outcome(self, lecture_id: str) -> dict | None:
        """What the lecture looks like on disk now the job is over.

        ``produce.py`` exits non-zero both when it crashed and when it merely left
        slides held back, so the exit code alone cannot tell the professor which of
        the two happened; this snapshot can.
        """
        from lecture_auto.web.store import get_lecture, lecture_summary

        try:
            summary = lecture_summary(self.settings, get_lecture(self.settings, lecture_id))
        except Exception as e:  # noqa: BLE001 - a bad snapshot must not leave the job "running" forever
            return {"error": repr(e)}
        return {
            "video_state": summary["video_state"],
            "held_back": len(summary["held_back"]),
            "no_audio": len(summary["no_audio"]),
            "scripts": summary["scripts"],
            "audio": summary["audio"],
            "candidates": summary["candidates"],
        }

    def list(self) -> list[dict]:
        with self._lock:
            return sorted((dict(j) for j in self._jobs.values()), key=lambda j: j["created_at"], reverse=True)

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def wait(self, job_id: str, statuses: tuple[str, ...], timeout: float) -> dict:
        with self._lock:
            self._lock.wait_for(lambda: self._jobs[job_id]["status"] in statuses, timeout=timeout)
            return dict(self._jobs[job_id])

    def active(self) -> bool:
        with self._lock:
            return any(j["status"] in ACTIVE for j in self._jobs.values())

    def busy(self, lecture_id: str) -> dict | None:
        with self._lock:
            for job in self._jobs.values():
                if job["lecture_id"] == lecture_id and job["status"] in ACTIVE:
                    return dict(job)
        return None

    def submit(self, kind: str, item: dict, slides: list[int] | None = None) -> dict:
        argv = job_argv(self.settings, kind, item["id"], slides)
        job = {
            "id": time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
            "kind": kind,
            "label": KINDS[kind],
            "lecture_id": item["id"],
            "slides": sorted(set(slides)) if slides else None,
            "argv": argv,
            "env": {k: v for k, v in job_env(self.settings, item).items() if k.startswith(("LECTURE_AUTO_", "CUDA_"))},
            "status": "queued",
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "pid": None,
        }
        with self._lock:
            if any(j["lecture_id"] == item["id"] and j["status"] in ACTIVE for j in self._jobs.values()):
                raise JobError("이 강의에 이미 대기 중이거나 실행 중인 작업이 있습니다")
            self._jobs[job["id"]] = job
            self._save(job)
            self._items[job["id"]] = item
            self._lock.notify_all()
        return dict(job)

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job["status"] == "queued":
                self._finish(job, "cancelled", None)
                self._lock.notify_all()
                return dict(job)
            if job["status"] != "running":
                raise JobError("이미 끝난 작업입니다")
            job["cancel_requested"] = True
            self._save(job)
            pid = job["pid"]
            if pid is None:
                return dict(job)
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        threading.Timer(KILL_GRACE_SECONDS, self._force_kill, args=(job_id, pid)).start()
        return self.get(job_id)

    def _force_kill(self, job_id: str, pid: int) -> None:
        job = self.get(job_id)
        if job and job["status"] == "running" and job["pid"] == pid:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _next(self) -> dict | None:
        if any(j["status"] == "running" for j in self._jobs.values()):
            return None
        queued = [j for j in self._jobs.values() if j["status"] == "queued"]
        return min(queued, key=lambda j: j["created_at"]) if queued else None

    def _loop(self) -> None:
        while True:
            with self._lock:
                while not self._stop and (job := self._next()) is None:
                    adopted = [j for j in self._jobs.values() if j["status"] == "running" and j["id"] not in self._procs]
                    self._lock.wait(timeout=5 if adopted else None)
                    for j in adopted:
                        if not _pid_alive(j.get("pid")):
                            self._finish(j, "interrupted", None)
                if self._stop:
                    return
                item = self._items.pop(job["id"], None)
                job.update(status="running", pid=None, started_at=time.time())
                self._save(job)
            try:
                self._run(job, item)
            except Exception as e:  # noqa: BLE001 - one broken job must not stop the only runner thread
                with self._lock:
                    self._procs.pop(job["id"], None)
                    self._finish(job, "failed", None, {"error": repr(e)})

    def _run(self, job: dict, item: dict | None) -> None:
        from lecture_auto.web.store import LectureNotFound, get_lecture

        try:
            item = item or get_lecture(self.settings, job["lecture_id"])
        except LectureNotFound:
            with self._lock:
                self._finish(job, "failed", None)
            return
        log = self.log_path(job["id"]).open("ab")
        log.write(f"$ {' '.join(job['argv'])}\n".encode())
        log.flush()
        try:
            proc = subprocess.Popen(
                job["argv"], cwd=self.settings.root, env=job_env(self.settings, item),
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
            )
        except OSError as e:
            log.write(f"실행 실패: {e}\n".encode())
            log.close()
            with self._lock:
                self._finish(job, "failed", None)
            return
        with self._lock:
            job["pid"] = proc.pid
            self._procs[job["id"]] = proc
            self._save(job)
            self._lock.notify_all()
            cancel_now = job.get("cancel_requested")
        if cancel_now:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            threading.Timer(KILL_GRACE_SECONDS, self._force_kill, args=(job["id"], proc.pid)).start()
        code = proc.wait()
        log.close()
        outcome = self._outcome(job["lecture_id"])
        with self._lock:
            self._procs.pop(job["id"], None)
            if job.get("cancel_requested"):
                status = "cancelled"
            else:
                status = "succeeded" if code == 0 else "failed"
            self._finish(job, status, code, outcome)
            self._lock.notify_all()

    def read_log(self, job_id: str, offset: int, limit: int = 256 * 1024) -> tuple[str, int]:
        path = self.log_path(job_id)
        if not path.exists():
            return "", offset
        if offset < 0:  # the last -offset bytes: where a long log keeps its error
            offset = max(path.stat().st_size + offset, 0)
        with path.open("rb") as f:
            f.seek(offset)
            chunk = f.read(limit)
        if len(chunk) == limit and b"\n" in chunk:
            chunk = chunk[: chunk.rfind(b"\n") + 1]
        # A chunk can end inside a multi-byte character; leave those bytes for the next read.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        text = decoder.decode(chunk)
        return text, offset + len(chunk) - len(decoder.getstate()[0])
