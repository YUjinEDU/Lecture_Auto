"""Pydantic models for script CRUD operations.

Exports:
    ScriptUpdateRequest  -- PUT body for editing a slide's script
    ScriptResponse       -- GET response for a single slide's script
    ScriptApproveResponse -- POST response for approving all scripts
"""

from pydantic import BaseModel


class ScriptUpdateRequest(BaseModel):
    """Request body for updating a slide's script text."""

    script: str
    keywords: list[str] | None = None
    transition_to_next: str | None = None


class ScriptResponse(BaseModel):
    """Response model for a single slide's script."""

    slide_index: int
    slide_number: int
    target_seconds: float
    script: str
    keywords: list[str]
    transition_to_next: str
    edited: bool = False
    edited_at: str | None = None


class ScriptApproveResponse(BaseModel):
    """Response model for script approval endpoint."""

    job_id: str
    total_slides: int
    tts_task_id: str | None = None
    status: str  # "approved"
