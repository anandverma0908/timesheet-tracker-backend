"""
app/main.py — Clean FastAPI application factory.

Entry point:
  uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import Base, engine
from app.api.router import api_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Trackly API…")

    # Ensure all ORM models are registered with Base.metadata before create_all
    import app.models  # noqa: F401 — side-effect: registers all models

    # Create any tables that don't exist yet (idempotent; Alembic handles migrations)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified")

    # Ensure upload directory exists
    import os
    os.makedirs(settings.upload_dir, exist_ok=True)

    # Start background scheduler
    from app.jobs.scheduler import start_scheduler
    start_scheduler()

    yield

    # Shutdown
    from app.jobs.scheduler import stop_scheduler
    stop_scheduler()
    logger.info("Trackly API shut down")


# ── Application factory ───────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Trackly — Work OS API",
        description="AI-powered Knowledge Management System · Powered by NOVA",
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS — tighten to frontend_url in production
    origins = ["*"] if settings.dev_mode else [settings.frontend_url]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # All API routes under /api/*
    app.include_router(api_router)

    # Serve uploaded files as static assets
    import os
    os.makedirs(settings.upload_dir, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

    # Health check (no auth — used by load balancers and Docker healthcheck)
    @app.get("/api/health", tags=["health"])
    async def health():
        from app.ai.nova import is_available
        return {
            "status":  "ok",
            "version": settings.app_version,
            "nova":    "online" if is_available() else "offline",
        }

    return app


app = create_app()
