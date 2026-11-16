"""Slide-level progress of a running voice job, read from what the job leaves on disk.

produce runs its workers in claim mode: each slide it takes (cached ones included) gets an
``audio/.claim/slide_NNN.done`` marker when its synthesis ends. regen rewrites the QC record of
every slide it was asked for. Approved slides are skipped by produce, so they are not counted.
"""
from __future__ import annotations

import re
import time

from lecture_auto.pipeline.approval import load_approvals
from lecture_auto.web.settings import Settings

_SLIDE = re.compile(r"slide_(\d{3})")


def _slides_touched_since(paths, since: float) -> set[int]:
    return {int(m.group(1)) for p in paths if (m := _SLIDE.match(p.name)) and p.stat().st_mtime >= since}


def job_progress(settings: Settings, job: dict, now: float | None = None) -> dict | None:
    started = job.get("started_at")
    if job.get("status") != "running" or not started or job.get("kind") not in ("produce", "regen"):
        return None
    work = settings.work_dir / job["lecture_id"]
    audio = work / "audio"
    if job["kind"] == "regen":
        scope = set(job.get("slides") or [])
        done = _slides_touched_since(audio.glob("slide_*.qc.json"), started) & scope
    else:
        slides = {int(m.group(1)) for p in (work / "rendered").glob("slide_*.png") if (m := _SLIDE.match(p.name))}
        scope = slides - set(load_approvals(work, job["lecture_id"]).slides)
        done = _slides_touched_since((audio / ".claim").glob("slide_*.done"), started) & scope
    if not scope:
        return None
    elapsed = max(0.0, (now if now is not None else time.time()) - started)
    remaining = len(scope) - len(done)
    eta = round(elapsed / len(done) * remaining) if done and remaining else None
    return {"done": len(done), "total": len(scope), "eta_seconds": eta}
