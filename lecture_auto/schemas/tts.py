"""Pydantic models for TTS API operations.

Exports:
    VoiceRegisterResponse  -- Response after registering a voice reference
    TTSStatusResponse      -- Status of TTS processing for a job
    TTSRegenerateResponse  -- Response after requesting single-slide re-TTS
    PackageResponse        -- Final package download info
"""

from pydantic import BaseModel


class VoiceRegisterResponse(BaseModel):
    """Response model for voice reference registration."""

    professor_id: str
    voice_ref_path: str
    status: str  # "registered"


class TTSStatusResponse(BaseModel):
    """Response model for TTS job status queries."""

    job_id: str
    task_id: str | None = None
    total_slides: int
    completed_slides: int
    status: str  # "pending" | "processing" | "complete" | "error"


class TTSRegenerateResponse(BaseModel):
    """Response model for single-slide TTS regeneration."""

    job_id: str
    slide_number: int
    task_id: str
    status: str  # "regenerating"


class PackageResponse(BaseModel):
    """Response model for final package download."""

    job_id: str
    files: list[str]
    total_size_mb: float
    download_url: str
