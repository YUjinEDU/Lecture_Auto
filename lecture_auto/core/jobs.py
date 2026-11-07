"""The contract between the web job queue and a job process: one JSON file per job, run by
``python -m lecture_auto.core.worker <file>``. ``command`` is the only place that knows
which production entry point and flags a kind of job means."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lecture_auto.pipeline.cache import write_text_atomic

JobKind = Literal["scripts", "produce", "regen", "heal", "assemble", "check", "study", "intent"]


class JobSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: JobKind
    project_id: str
    slides: list[int] | None = None
    workers_per_gpu: int | None = Field(default=None, ge=1)
    force: bool = False

    def model_post_init(self, _context) -> None:
        if self.kind == "regen" and (not self.slides or any(n < 1 for n in self.slides)):
            raise ValueError("regen needs one or more slide numbers >= 1")
        if self.force and self.kind != "intent":
            raise ValueError("force is only supported for intent")


def command(spec: JobSpec) -> tuple[Literal["batch", "produce"], list[str]]:
    only = ["--only", spec.project_id]
    if spec.kind == "intent":
        return "batch", only + ["--intent"] + (["--force-intent"] if spec.force else [])
    if spec.kind == "produce":
        workers = ["--workers-per-gpu", str(spec.workers_per_gpu)] if spec.workers_per_gpu else []
        return "produce", only + ["--gpus", "0", "--fix-failed", "--heal"] + workers
    if spec.kind == "regen":
        slides = ",".join(str(n) for n in sorted(set(spec.slides or [])))
        return "batch", only + ["--slides", slides, "--gpu", "0"]
    tail = {
        "scripts": ["--skip-tts"],
        "heal": ["--heal", "--gpu", "0"],
        "assemble": ["--assemble-only"],
        "check": ["--check"],
        "study": ["--study"],
    }[spec.kind]
    return "batch", only + tail


def write_spec(spec: JobSpec, path: Path) -> None:
    write_text_atomic(path, spec.model_dump_json(indent=2))


def read_spec(path: Path) -> JobSpec:
    return JobSpec.model_validate_json(Path(path).read_text(encoding="utf-8"))
