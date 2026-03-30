"""Job status enum and progress event schema for async pipeline."""

from enum import Enum

from pydantic import BaseModel


class JobStatus(str, Enum):
    queued = "queued"
    started = "started"
    vlm_processing = "vlm_processing"
    script_generating = "script_generating"
    script_completed = "script_completed"
    completed = "completed"
    failed = "failed"


class ProgressEvent(BaseModel):
    job_id: str
    stage: str
    current: int
    total: int
    percent: float
    status: str  # "processing" | "done" | "skipped" | "error"
