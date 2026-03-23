from pydantic import BaseModel, Field
from typing import Literal
import uuid


class FontInfo(BaseModel):
    name: str | None = None
    size_pt: float | None = None
    bold: bool | None = None
    italic: bool | None = None


class TextRun(BaseModel):
    text: str
    font: FontInfo


class TextParagraph(BaseModel):
    runs: list[TextRun]
    full_text: str


class ShapeRecord(BaseModel):
    shape_id: int
    name: str
    z_order: int
    left: int    # EMU
    top: int
    width: int
    height: int
    content_source: Literal["text", "image", "chart", "smartart", "ole_object", "table", "other"]
    has_image: bool = False
    has_text: bool = False
    text_role: Literal["title", "body", "other"] | None = None
    paragraphs: list[TextParagraph] = Field(default_factory=list)


class SlideRecord(BaseModel):
    slide_index: int
    slide_number: int
    png_path: str
    shapes: list[ShapeRecord]


class LectureStyle(BaseModel):
    density: Literal["concise", "detailed"]
    tone: Literal["formal", "casual"]
    approach: Literal["explanatory", "socratic"]
    supplement: str = ""


class SlideManifest(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    file_sha256: str
    lecture_name: str
    subject_name: str
    target_audience: str
    target_minutes: int
    style: LectureStyle
    slide_count: int
    slides: list[SlideRecord]
    font_warnings: list[str] = Field(default_factory=list)
