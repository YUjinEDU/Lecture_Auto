"""FastAPI application entry point for Lecture Auto pipeline.

Provides CORS-enabled API with lifespan management (Redis cleanup on shutdown).
Auth middleware (Supabase JWT) is deferred to Phase 1 Plan 04 scope (INFRA-03).
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lecture_auto.api.deps import close_async_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: cleanup async Redis on shutdown."""
    yield
    await close_async_redis()


app = FastAPI(
    title="Lecture Auto API",
    description="Lecture automation pipeline - PPTX to script and audio",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from lecture_auto.api.routes import jobs, scripts  # noqa: E402

app.include_router(jobs.router)
app.include_router(scripts.router)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "0.3.0"}
