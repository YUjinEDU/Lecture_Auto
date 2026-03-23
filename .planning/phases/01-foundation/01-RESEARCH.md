# Phase 1: Foundation - Research

**Researched:** 2026-03-23
**Domain:** PPTX parsing, LibreOffice headless rendering, FastAPI file upload, Supabase JWT auth, Pydantic v2 schemas
**Confidence:** HIGH (core stack verified), MEDIUM (Korean font detection heuristic)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01/D-02/D-03:** 설명 스타일 — 밀도/말투/접근방식 3축, 프리셋 + 자유 텍스트, 강의 전체 단일 적용
- **D-04:** Shape metadata 최대 수준: shape type + bounding box(left/top/width/height) + z-order + font 정보
- **D-05:** 발표자 노트(speaker notes) 스키마 제외
- **D-06:** 이미지 shape는 `has_image: true` 플래그만 포함
- **D-07:** 텍스트 박스를 제목/본문/기타로 구분된 구조화된 배열로 분리
- **D-08:** 파일 + 메타데이터 단일 요청으로 전송
- **D-09:** 업로드 즉시 동기 파싱 후 Slide Manifest JSON 반환 (Phase 1 동기)
- **D-10:** 중복 파일 감지 시 경고 후 사용자 선택
- **D-11:** 결과 확인은 포털 UI 상태 폴링 방식
- **D-12:** 렌더링된 PNG에서 깨진 문자(□□□) 자동 감지
- **D-13:** 폰트 깨짐 시 경고 로그만 남기고 파이프라인 계속 진행
- **D-14:** GPU 서버에 주요 한국어 폰트 신규 설치 필요 (나눔고딕, 맑은고딕 등)
- Phase 1은 동기 처리 (Celery 없음 — BackgroundTasks도 금지, 직접 동기 실행)
- python-pptx for parsing, LibreOffice headless for rendering, pdf2image for PNG
- FastAPI 0.135.1, Pydantic v2, Supabase Auth professor role JWT validation
- Local disk at /data/work/{job_id}/

### Claude's Discretion
- job_id 형식 (UUID v4)
- Supabase jobs 테이블 컬럼 구조 및 상태값 (pending/processing/done/failed)
- Pydantic 스키마 필드명 및 타입 상세
- LibreOffice → PDF → PNG 변환 DPI 설정
- 깨진 문자 감지 방법 (OCR vs. 텍스트 추출 비교)
- Python 패키지 구조 및 디렉토리 레이아웃

### Deferred Ideas (OUT OF SCOPE)
- 파싱/렌더링 완료 시 알림 (이메일/포털 내 알림) — Phase 3 UI에서 검토
- 같은 PPTX 재실행 이력 관리 — 백로그 추가
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INPUT-01 | PPTX 파일 1개 업로드 | FastAPI UploadFile + Form() multipart pattern |
| INPUT-02 | 강의명, 과목명, 수강 대상, 목표 시간, 설명 스타일 입력 | FastAPI Form() fields alongside UploadFile |
| PARSE-01 | 제목, 본문, 발표자 노트 제외, shape metadata 추출 | python-pptx shape iteration, text_frame, font, EMU bounding box |
| PARSE-02 | SmartArt, 차트, OLE shape-type 감지 및 플래그 | has_smart_art, has_chart, MSO_SHAPE_TYPE enum detection |
| PARSE-03 | Slide Manifest JSON Pydantic 스키마 검증 후 저장 | Pydantic v2 model_validate, JSON serialization |
| RENDER-01 | 슬라이드 PNG 렌더링 (LibreOffice CLI) | soffice --headless → PDF → pdf2image convert_from_path |
| RENDER-02 | 한국어 폰트 정상 렌더링 검증 | fonts-noto-cjk apt install + heuristic tofu detection |
| RENDER-03 | 슬라이드 번호 매칭 파일명 보장 | pdf2image output_folder + zero-padded naming |
| INFRA-01 | FastAPI REST API | FastAPI 0.135.1 + uvicorn |
| INFRA-03 | Supabase Auth professor role 접근 제한 | PyJWT HS256 decode, app_metadata role claim check |
| INFRA-04 | 중간 산출물 GPU 서버 로컬 디스크 저장 | pathlib.Path /data/work/{job_id}/ |
| INFRA-05 | 각 단계 실행 로그 저장 | Python logging to file per job_id |
</phase_requirements>

---

## Summary

Phase 1 builds the parsing and rendering infrastructure: receive a PPTX file, extract structured shape metadata as a validated JSON manifest, render each slide to PNG, and expose a FastAPI endpoint secured by Supabase Auth JWT. No GPU models are involved.

The pipeline is deliberately synchronous in Phase 1. The FastAPI endpoint receives the file and form data, runs python-pptx parsing inline, shells out to LibreOffice headless for rendering, and returns the manifest JSON in the same HTTP response. This keeps the architecture simple before Celery is added in Phase 2.

The three highest-risk items are: (1) LibreOffice concurrent process isolation — a single soffice process per conversion with a dedicated `--env:UserInstallation` directory is mandatory to avoid lock-file races; (2) Korean font availability — `fonts-noto-cjk` must be installed on the GPU server before LibreOffice will render Korean glyphs correctly; (3) Supabase JWT verification — the correct pattern uses PyJWT with `audience="authenticated"` and a role check against `app_metadata.role`.

**Primary recommendation:** Use the PPTX → PDF (LibreOffice) → PNG (pdf2image, DPI=150) pipeline. Never use LibreOffice direct-to-PNG (exports only the first slide). Always isolate soffice per job with `--env:UserInstallation=/tmp/soffice-{job_id}`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| python-pptx | 1.0.2 | PPTX shape/text/metadata extraction | Only mature maintained Python PPTX library; v1.0 stable API |
| LibreOffice (soffice) | system 7.6+ | PPTX → PDF headless conversion | Only FOSS tool that handles complex PPTX layouts on Linux |
| pdf2image | 1.17+ | PDF → per-slide PNG via poppler pdftoppm | Battle-tested, PIL-compatible, per-page output with DPI control |
| Pillow | 11.x | Image loading for tofu detection | Required pdf2image backend; used for pixel-level analysis |
| poppler-utils | system | Binary dependency for pdf2image | Best PDF rasteriser on Linux |
| FastAPI | 0.135.1 | REST API endpoint | Specified in stack; async-capable, auto-docs |
| pydantic | 2.x (bundled) | Slide Manifest schema + request validation | Bundled with FastAPI; v2 is 5–20x faster than v1 |
| PyJWT | 2.x | Supabase JWT verification | Standard Python JWT library; HS256 with audience support |
| python-dotenv | 1.x | .env loading on GPU server | Secrets management |
| python-multipart | latest | FastAPI multipart form/file upload | Required by FastAPI for UploadFile + Form() |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| hashlib (stdlib) | — | SHA-256 file fingerprint for duplicate detection | Use `hashlib.file_digest()` (Python 3.11+) for memory-safe hashing |
| pathlib (stdlib) | — | /data/work/{job_id}/ path management | All file I/O path construction |
| uuid (stdlib) | — | job_id generation (UUID v4) | `uuid.uuid4()` for job identifiers |
| logging (stdlib) | — | Per-job structured log files | INFRA-05 execution logs |
| subprocess | stdlib | Shell out to soffice | Isolated per-conversion with timeout |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| LibreOffice → pdf2image | LibreOffice direct PNG | Direct PNG only exports slide 1; pdf2image gives all slides with DPI control |
| PyJWT | python-jose | python-jose is heavier; PyJWT is simpler, well-maintained, sufficient for HS256 |
| hashlib.file_digest | filename+size | SHA-256 is content-based (reliable); filename+size can have false negatives |

**Installation:**
```bash
# System packages (GPU server)
sudo apt install libreoffice poppler-utils fonts-noto-cjk fonts-nanum

# Python packages
pip install python-pptx==1.0.2 pdf2image Pillow fastapi uvicorn python-multipart pydantic PyJWT python-dotenv supabase
```

---

## Architecture Patterns

### Recommended Project Structure
```
lecture_auto/
├── api/
│   ├── main.py              # FastAPI app, lifespan, router registration
│   ├── deps.py              # get_current_professor dependency (JWT)
│   └── routes/
│       └── upload.py        # POST /upload endpoint
├── pipeline/
│   ├── parser.py            # python-pptx → SlideManifest
│   ├── renderer.py          # LibreOffice → PDF → pdf2image → PNGs
│   └── tofu_detector.py     # Korean tofu pixel heuristic
├── schemas/
│   ├── manifest.py          # Pydantic v2 SlideManifest, ShapeRecord, etc.
│   └── request.py           # UploadRequest form fields
├── storage/
│   └── jobs.py              # /data/work/{job_id}/ path helpers
└── .env                     # SUPABASE_URL, SUPABASE_JWT_SECRET, JOB_OUTPUT_ROOT
```

### Pattern 1: FastAPI File Upload + Form Fields (Synchronous)

FastAPI does NOT support Pydantic models as Form parameters. Use explicit `Form()` for each field alongside `UploadFile`.

```python
# Source: https://fastapi.tiangolo.com/tutorial/request-files/
from fastapi import APIRouter, UploadFile, File, Form, Depends
from schemas.manifest import SlideManifest
from api.deps import get_current_professor

router = APIRouter()

@router.post("/upload", response_model=SlideManifest)
async def upload_pptx(
    file: UploadFile = File(...),
    lecture_name: str = Form(...),
    subject_name: str = Form(...),
    target_audience: str = Form(...),
    target_minutes: int = Form(...),
    style_density: str = Form(...),        # "concise" | "detailed"
    style_tone: str = Form(...),           # "formal" | "casual"
    style_approach: str = Form(...),       # "explanatory" | "socratic"
    style_supplement: str = Form(""),      # free text supplement
    professor=Depends(get_current_professor),
):
    ...
```

**Requirement:** `python-multipart` must be installed or FastAPI raises a 422 at startup.

### Pattern 2: Supabase JWT Verification (FastAPI Dependency)

Supabase JWTs use HS256. The JWT secret is in the Supabase project dashboard under Settings > API > JWT Secret. Custom roles are stored in `app_metadata.role` via a Custom Access Token Hook.

```python
# Source: https://dev.to/zwx00/validating-a-supabase-jwt-locally-with-python-and-fastapi-59jf
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os

security = HTTPBearer()

def get_current_professor(
    cred: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    try:
        payload = jwt.decode(
            cred.credentials,
            os.environ["SUPABASE_JWT_SECRET"],
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    role = payload.get("app_metadata", {}).get("role")
    if role != "professor":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Professor role required")

    return payload
```

**Key detail:** Supabase uses `audience="authenticated"` on all user JWTs. Omitting this causes decode failure. Role must be set via a Custom Access Token Hook in Supabase Auth → Hooks, not via `user_metadata` (which is user-editable).

### Pattern 3: python-pptx Shape Iteration and Type Detection

```python
# Source: https://python-pptx.readthedocs.io/en/latest/api/shapes.html
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.util import Emu

def classify_shape(shape) -> dict:
    base = {
        "shape_id": shape.shape_id,
        "name": shape.name,
        # Z-order: index in shapes collection (0 = backmost)
        # Pass index from enumerate(slide.shapes) at call site
        "left": shape.left,   # EMU integer
        "top": shape.top,
        "width": shape.width,
        "height": shape.height,
    }

    # SmartArt: shape_type is None on GraphicFrame when not chart/table/OLE
    if shape.shape_type == MSO_SHAPE_TYPE.IGX_GRAPHIC or (
        hasattr(shape, "has_smart_art") and shape.has_smart_art
    ):
        return {**base, "content_source": "smartart", "has_text": False}

    if hasattr(shape, "has_chart") and shape.has_chart:
        return {**base, "content_source": "chart", "has_text": False}

    if shape.shape_type in (
        MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT,
        MSO_SHAPE_TYPE.LINKED_OLE_OBJECT,
    ):
        return {**base, "content_source": "ole_object", "has_text": False}

    if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
        return {**base, "content_source": "image", "has_image": True, "has_text": False}

    if shape.has_text_frame:
        return {**base, "content_source": "text", **extract_text(shape)}

    return {**base, "content_source": "other", "has_text": False}
```

**Critical:** `has_smart_art` returns `True` only in python-pptx 1.0+. In 0.6.x, SmartArt GraphicFrame shapes return `None` for `shape_type` — handle both cases.

### Pattern 4: LibreOffice Headless Conversion (Isolated)

```python
# Source: Community docs + LibreOffice bug #82775 (concurrent crash fix)
import subprocess
import tempfile
import shutil
from pathlib import Path

def pptx_to_pdf(pptx_path: Path, output_dir: Path, job_id: str) -> Path:
    # Each conversion gets its own UserInstallation to avoid lock file races
    user_install = Path(f"/tmp/soffice-{job_id}")
    user_install.mkdir(exist_ok=True)
    try:
        result = subprocess.run(
            [
                "soffice",
                "--headless",
                "--norestore",
                "--nofirststartwizard",
                f"--env:UserInstallation=file://{user_install}",
                "--convert-to", "pdf",
                "--outdir", str(output_dir),
                str(pptx_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"soffice failed: {result.stderr}")
    finally:
        shutil.rmtree(user_install, ignore_errors=True)

    pdf_path = output_dir / pptx_path.with_suffix(".pdf").name
    if not pdf_path.exists():
        raise FileNotFoundError(f"Expected PDF not found: {pdf_path}")
    return pdf_path
```

### Pattern 5: PDF → Numbered PNG Slides

```python
# Source: https://pdf2image.readthedocs.io/en/latest/reference.html
from pdf2image import convert_from_path
from pathlib import Path

def pdf_to_pngs(pdf_path: Path, output_dir: Path, dpi: int = 150) -> list[Path]:
    images = convert_from_path(str(pdf_path), dpi=dpi)
    paths = []
    for idx, img in enumerate(images, start=1):
        out = output_dir / f"slide_{idx:03d}.png"
        img.save(str(out), "PNG")
        paths.append(out)
    return paths
```

**DPI recommendation:** 150 DPI produces 1588×1191px for a 16:9 slide — sufficient for VLM in Phase 2. 200 DPI doubles file size with minimal quality gain for this use case.

### Pattern 6: Korean Tofu Detection Heuristic

OCR is overkill for detecting rendering failures. Use a pixel-level approach: tofu characters (□) render as uniform gray/white rectangles with sharp edges. The practical approach: compare the rendered PNG against a known-bad reference OR detect large uniform-color rectangular regions in text areas.

The simpler production approach is to check font substitution in the LibreOffice conversion log — LibreOffice prints "substituting font X with Y" warnings to stderr when a font is missing.

```python
# Approach: parse soffice stderr for font substitution warnings
def check_font_substitution(soffice_stderr: str) -> list[str]:
    """Returns list of substituted font warnings from LibreOffice stderr."""
    warnings = []
    for line in soffice_stderr.splitlines():
        if "substitut" in line.lower() or "font" in line.lower():
            warnings.append(line.strip())
    return warnings
```

For pixel-level detection (D-12), use Pillow to check if a region expected to have text is predominantly a single uniform color (indication of tofu blocks):

```python
from PIL import Image
import numpy as np

def has_tofu_regions(img_path: Path, threshold: float = 0.95) -> bool:
    """Heuristic: high proportion of uniform-gray pixels in a slide suggests tofu rendering."""
    img = Image.open(img_path).convert("L")  # grayscale
    arr = np.array(img)
    # Tofu □ characters are typically rendered as white or light-gray boxes
    # Check for unexpectedly high ratio of near-white pixels in a non-blank slide
    white_ratio = (arr > 240).sum() / arr.size
    # A slide with >95% near-white pixels is likely blank or all-tofu
    return white_ratio > threshold
```

**Note:** This heuristic is LOW confidence — it will not catch partial tofu (a few broken characters in a dense slide). The recommended primary detection is soffice stderr font substitution parsing (MEDIUM confidence).

### Pattern 7: Pydantic v2 Slide Manifest Schema

```python
# Pydantic v2 — field names and types at Claude's discretion per CONTEXT.md D-decisions
from pydantic import BaseModel, Field
from typing import Literal
import uuid

class FontInfo(BaseModel):
    name: str | None = None
    size_pt: float | None = None  # converted from EMU: Pt(run.font.size).pt if not None
    bold: bool | None = None
    italic: bool | None = None

class TextRun(BaseModel):
    text: str
    font: FontInfo

class TextParagraph(BaseModel):
    runs: list[TextRun]
    full_text: str  # "".join(run.text for run in runs)

class ShapeRecord(BaseModel):
    shape_id: int
    name: str
    z_order: int                   # index in shapes collection, 0 = backmost
    left: int                      # EMU
    top: int
    width: int
    height: int
    content_source: Literal[
        "text", "image", "chart", "smartart", "ole_object", "table", "other"
    ]
    has_image: bool = False
    has_text: bool = False
    text_role: Literal["title", "body", "other"] | None = None
    paragraphs: list[TextParagraph] = Field(default_factory=list)

class SlideRecord(BaseModel):
    slide_index: int               # 0-based
    slide_number: int              # 1-based
    png_path: str                  # relative to job_dir: "slide_001.png"
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
```

**Pydantic v2 validation:** Use `SlideManifest.model_validate(data)` not the v1 `parse_obj()`. Serialize with `manifest.model_dump_json()` for file storage.

### Pattern 8: Duplicate File Detection

```python
import hashlib
from pathlib import Path

def compute_sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()  # Python 3.11+
```

Store `file_sha256` in the Supabase `jobs` table. On upload, query for existing jobs with the same hash for the same user. Return a 409 with existing job_id if found — let the frontend prompt "같은 파일이 있습니다, 새로 만들까요?"

### Anti-Patterns to Avoid

- **LibreOffice direct PNG:** `--convert-to png` on a PPTX outputs only the first slide. Always go through PDF first.
- **No UserInstallation isolation:** Running concurrent soffice without `--env:UserInstallation` causes lock file races and zero-byte PDF outputs (documented bug #82775).
- **pptx.has_smart_art on 0.6.x:** The `has_smart_art` property does not exist in python-pptx 0.6.x. Pin to 1.0.2.
- **Form + Pydantic model:** FastAPI rejects Pydantic models as Form() parameters. Use individual `Form(...)` fields.
- **Omitting `audience="authenticated"` in PyJWT:** Supabase JWTs will fail to decode without this — PyJWT treats the audience claim as a required validation step.
- **Reading role from `user_metadata`:** `user_metadata` is user-editable. Role must live in `app_metadata` set via an Auth Hook.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PPTX parsing | Custom XML parser | python-pptx 1.0.2 | OOXML spec is 6000+ pages; EMU handling, shape tree traversal are non-trivial |
| PPTX → image | Custom renderer | LibreOffice + pdf2image | Font embedding, theme resolution, layout rendering require a full presentation engine |
| JWT decode + verify | Custom base64 decode | PyJWT | Signature verification, expiry, audience checks — all handled; hand-rolling introduces security holes |
| File deduplication | Filename comparison | hashlib SHA-256 | Filename collisions are common; content hash is definitive |
| Per-slide PNG naming | Custom counter | pdf2image output_folder + manual index | pdf2image returns PIL images in order; naming is trivial to control |

---

## Common Pitfalls

### Pitfall 1: LibreOffice Lock File Race Condition
**What goes wrong:** Two concurrent soffice processes share the same `~/.config/libreoffice/` profile directory. One creates a lock file; the other fails with "source file could not be loaded" or produces a zero-byte PDF.
**Why it happens:** LibreOffice's user profile is not designed for concurrent access.
**How to avoid:** Pass `--env:UserInstallation=file:///tmp/soffice-{job_id}` to every soffice invocation. Clean up the temp dir after conversion.
**Warning signs:** Zero-byte PDF output; soffice exits with non-zero code without a clear error.

### Pitfall 2: Korean Fonts Not Installed Before LibreOffice Is Invoked
**What goes wrong:** LibreOffice substitutes missing Korean fonts with a Latin fallback, rendering Korean text as □□□ (tofu) silently. No error is raised.
**Why it happens:** PPTX files embed font references but not the font files themselves. LibreOffice must find the fonts on the system.
**How to avoid:** Install `fonts-noto-cjk` and `fonts-nanum` before running any rendering. Run `fc-cache -f -v` after installation. Verify with `fc-list | grep -i korean`.
**Warning signs:** soffice stderr contains "substituting font"; PNG shows rectangular gray blocks where Korean text should be.

### Pitfall 3: SmartArt Shape Type Returns None
**What goes wrong:** Code checks `shape.shape_type == MSO_SHAPE_TYPE.IGX_GRAPHIC` but gets `None` on python-pptx 0.6.x. The shape is silently classified as "other" and not flagged.
**Why it happens:** GraphicFrame shapes that contain SmartArt return `None` for `shape_type` in python-pptx 0.6.x. python-pptx 1.0.x adds `has_smart_art`.
**How to avoid:** Pin to python-pptx 1.0.2. Always use `has_smart_art` property, not shape_type comparison, for SmartArt detection.
**Warning signs:** Slides with SmartArt produce no `content_source: "smartart"` records in the manifest.

### Pitfall 4: Supabase JWT audience Mismatch
**What goes wrong:** `jwt.decode()` raises `InvalidAudienceError` at runtime even though the token looks valid.
**Why it happens:** Supabase embeds `"aud": "authenticated"` in all user JWTs. PyJWT enforces audience validation when the payload has an `aud` claim.
**How to avoid:** Always pass `audience="authenticated"` to `jwt.decode()`.
**Warning signs:** 401 errors on all authenticated requests; PyJWT raises `jwt.exceptions.InvalidAudienceError`.

### Pitfall 5: FastAPI Form + File Mixed Request Without python-multipart
**What goes wrong:** FastAPI raises a 422 Unprocessable Entity or a startup error mentioning `python-multipart`.
**Why it happens:** FastAPI delegates multipart parsing to `python-multipart`, which is not installed by default.
**How to avoid:** Include `python-multipart` in requirements. Test the upload endpoint at project start.
**Warning signs:** Startup warning "Form data requires 'python-multipart' to be installed".

### Pitfall 6: EMU Values Stored as Raw Integers in JSON
**What goes wrong:** Downstream consumers (VLM prompts, frontend) receive large integers like `914400` and cannot interpret them without knowing the EMU/pt conversion.
**Why it happens:** python-pptx returns positions/sizes as `Emu` integers natively.
**How to avoid:** Store EMU values as-is in the manifest (they're precise and reversible), but include a `slide_width_emu` / `slide_height_emu` header field for relative positioning. Optionally add a `left_pct` / `top_pct` derived field for convenience.
**Warning signs:** Frontend or VLM cannot interpret bounding boxes.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| python-pptx 0.6.x | python-pptx 1.0.2 | 2024 | `has_smart_art` property available; stable v1 API |
| Pydantic v1 `.parse_obj()` | Pydantic v2 `.model_validate()` | 2023 | 5–20x faster; breaking API changes |
| `hashlib.new("sha256")` + manual chunk loop | `hashlib.file_digest(f, "sha256")` | Python 3.11 (2022) | Cleaner; memory-safe for large files |
| LibreOffice direct PNG (`--convert-to png`) | LibreOffice → PDF → pdf2image | Always | Direct PNG only exports slide 1 |

**Deprecated/outdated:**
- python-pptx `parse_obj()`: replaced by `model_validate()` in Pydantic v2
- `python-jose`: heavier than PyJWT; use PyJWT for simple HS256 Supabase JWT verification

---

## Open Questions

1. **Supabase Auth Hook deployment status**
   - What we know: The professor role must be in `app_metadata`, set via a Custom Access Token Hook
   - What's unclear: Whether the existing lab portal's Supabase project already has this hook configured
   - Recommendation: Before Phase 1 implementation, verify the hook exists; if not, set it up as a Wave 0 task

2. **맑은고딕 (Malgun Gothic) availability on Ubuntu**
   - What we know: Malgun Gothic is a Microsoft-owned font; not freely redistributable on Linux
   - What's unclear: Whether PPTX files from lab use Malgun Gothic exclusively or also open fonts
   - Recommendation: Install `fonts-nanum` (Nanum Gothic) as open fallback; test representative PPTX files before declaring Phase 1 complete

3. **GPU server LibreOffice version**
   - What we know: Stack requires 7.6+
   - What's unclear: What version is currently installed on the GPU server
   - Recommendation: Run `soffice --version` as a Wave 0 check; upgrade if below 7.6

4. **tofu detection threshold calibration**
   - What we know: The pixel heuristic (white ratio > 0.95) is a crude approximation
   - What's unclear: What ratio is appropriate for typical lecture slides (which may legitimately have white backgrounds)
   - Recommendation: Primary detection should be soffice stderr font substitution parsing; pixel heuristic is secondary

---

## Sources

### Primary (HIGH confidence)
- [python-pptx 1.0.0 Shapes API](https://python-pptx.readthedocs.io/en/latest/api/shapes.html) — shape properties, has_smart_art, has_chart, bounding box
- [python-pptx MSO_SHAPE_TYPE enum](https://python-pptx.readthedocs.io/en/latest/api/enum/MsoShapeType.html) — all shape type values
- [FastAPI Request Files docs](https://fastapi.tiangolo.com/tutorial/request-files/) — UploadFile + Form() pattern
- [pdf2image PyPI / readthedocs](https://pdf2image.readthedocs.io/en/latest/reference.html) — convert_from_path DPI parameter
- [Supabase JWT Docs](https://supabase.com/docs/guides/auth/jwts) — HS256, audience="authenticated"
- [Supabase Custom Claims RBAC Docs](https://supabase.com/docs/guides/database/postgres/custom-claims-and-role-based-access-control-rbac) — app_metadata role pattern

### Secondary (MEDIUM confidence)
- [Validating Supabase JWT with FastAPI (DEV.to)](https://dev.to/zwx00/validating-a-supabase-jwt-locally-with-python-and-fastapi-59jf) — verified against Supabase official docs
- [LibreOffice concurrent conversion bug #82775](https://bugs.documentfoundation.org/show_bug.cgi?id=82775) — UserInstallation isolation pattern
- [Integrating FastAPI with Supabase Auth (DEV.to)](https://dev.to/j0/integrating-fastapi-with-supabase-auth-780) — FastAPI dependency pattern
- [fonts-noto-cjk Ubuntu package](https://launchpad.net/ubuntu/jammy/+package/fonts-noto-cjk) — Korean font installation

### Tertiary (LOW confidence)
- Pixel-level tofu detection heuristic — derived from general PIL image analysis; not verified against specific Korean PPTX rendering failures; flag for validation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified against PyPI and official docs
- Architecture: HIGH — patterns verified against FastAPI and python-pptx official docs
- Korean font setup: MEDIUM — documented issues with headless rendering; noto-cjk is the correct package but specific PPTX font coverage depends on the files used
- Tofu detection: LOW — heuristic approach only; stderr font substitution parsing is more reliable
- Supabase JWT pattern: HIGH — verified against official Supabase docs and community article

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable libraries; LibreOffice behavior unlikely to change)
