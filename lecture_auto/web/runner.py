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
import sys
import threading
import time
import uuid
from pathlib import Path

from lecture_auto.core.jobs import write_spec
from lecture_auto.web.job_process import (
    GPU_KINDS,
    KINDS,
    JobError,
    _pid_alive,
    _proc_identity,
    job_env,
    job_outcome,
    job_spec,
)
from lecture_auto.web.lecture_settings import NO_RAON
from lecture_auto.web.settings import Settings

WORKER = ["-m", "lecture_auto.core.worker"]
ACTIVE = ("queued", "running")
KILL_GRACE_SECONDS = 15


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
                if job["status"] == "running" and not _pid_alive(job.get("pid"), job.get("pid_id")):
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
        if kind in GPU_KINDS and not self.settings.raon_enabled and item.get("tts_engine", "raon") == "raon":
            raise JobError(NO_RAON)
        spec = job_spec(self.settings, kind, item["id"], slides)
        env = job_env(self.settings, item)
        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        spec_path = self.settings.jobs_dir / "specs" / f"{job_id}.json"
        argv = [self.settings.python, *WORKER, str(spec_path)]
        job = {
            "id": job_id,
            "kind": kind,
            "label": KINDS[kind],
            "lecture_id": item["id"],
            "owner": item.get("owner"),
            "slides": sorted(set(slides)) if slides else None,
            "argv": argv,
            "env": {k: env[k] for k in ("LECTURE_AUTO_PROJECTS", "CUDA_DEVICE_ORDER", "CUDA_VISIBLE_DEVICES")},
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
            write_spec(spec, spec_path)
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
            pid_id = job.get("pid_id")
            if pid is None:
                return dict(job)
        if not _pid_alive(pid, pid_id):
            # Nothing of ours answers on this pid any more (recycled after a crash or reboot):
            # never signal whatever process holds the number now.
            with self._lock:
                if job["status"] == "running":
                    self._finish(job, "interrupted", None)
            return self.get(job_id)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGTERM)
        threading.Timer(KILL_GRACE_SECONDS, self._force_kill, args=(job_id, pid)).start()
        return self.get(job_id)

    def _force_kill(self, job_id: str, pid: int) -> None:
        job = self.get(job_id)
        if job and job["status"] == "running" and job["pid"] == pid:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGKILL)

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
                        if not _pid_alive(j.get("pid"), j.get("pid_id")):
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
        env = job_env(self.settings, item)
        log = self.log_path(job["id"]).open("ab")
        log.write(f"$ {' '.join(job['argv'])}\n".encode())
        log.flush()
        try:
            read_fd, write_fd = os.pipe()
            with os.fdopen(read_fd, "rb") as ready, os.fdopen(write_fd, "wb") as sender:
                argv = [sys.executable, "-m", "lecture_auto.web.job_worker", str(write_fd), *job["argv"]]
                proc = subprocess.Popen(
                    argv, cwd=self.settings.root, env=env, pass_fds=(write_fd,),
                    stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                )
                sender.close()
                ready.readline()
        except OSError as e:
            log.write(f"실행 실패: {e}\n".encode())
            log.close()
            with self._lock:
                self._finish(job, "failed", None)
            return
        with self._lock:
            job["pid"] = proc.pid
            job["pid_id"] = _proc_identity(proc.pid)
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
        outcome = job_outcome(self.settings, job["lecture_id"])
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
