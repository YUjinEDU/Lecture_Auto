"""FastAPI application entry point for Lecture Auto pipeline.

Provides CORS-enabled API with lifespan management (Redis cleanup on shutdown).
Auth middleware (Supabase JWT) is deferred to Phase 1 Plan 04 scope (INFRA-03).
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from lecture_auto.api.deps import close_async_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: cleanup async Redis on shutdown."""
    yield
    await close_async_redis()


app = FastAPI(
    title="Lecture Auto API",
    description="Lecture automation pipeline - PPTX to script and audio",
    version="0.4.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from lecture_auto.api.routes import download, jobs, scripts, tts  # noqa: E402
from lecture_auto.api.routes import demo  # noqa: E402

app.include_router(jobs.router)
app.include_router(scripts.router)
app.include_router(tts.router)
app.include_router(download.router)
app.include_router(demo.router)

demo_static_dir = Path(__file__).resolve().parents[1] / "demo_static"
app.mount("/demo/assets", StaticFiles(directory=demo_static_dir), name="demo-assets")


@app.middleware("http")
async def no_cache_demo_assets(request: Request, call_next):
    """Disable browser caching for demo static assets during development."""
    response = await call_next(request)
    if request.url.path.startswith("/demo/assets/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.3.0"}
