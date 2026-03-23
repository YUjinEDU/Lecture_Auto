from pydantic import BaseModel


class UploadResponse(BaseModel):
    job_id: str
    status: str  # "completed" | "duplicate_warning"
    slide_count: int
    message: str
    manifest_path: str
    duplicate_of: str | None = None
