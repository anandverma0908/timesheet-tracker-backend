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

async def _bulk_embed_unindexed():
    """Embed all tickets and wiki pages that have no entry in their embeddings table yet."""
    try:
        from sqlalchemy import text as _text
        from app.core.database import SessionLocal
        from app.ai.search import embed_and_store_ticket, embed_and_store_wiki
        db = SessionLocal()
        try:
            # Tickets
            ticket_rows = db.execute(_text("""
                SELECT t.id, t.summary, t.description
                FROM jira_tickets t
                LEFT JOIN ticket_embeddings te ON te.ticket_id = t.id
                WHERE t.is_deleted = false AND te.ticket_id IS NULL
                LIMIT 500
            """)).fetchall()
            logger.info(f"Bulk embedding {len(ticket_rows)} un-indexed tickets…")
            for r in ticket_rows:
                try:
                    await embed_and_store_ticket(str(r.id), r.summary or "", r.description or "", db)
                except Exception as exc:
                    logger.warning(f"Auto-embed skipped for ticket {r.id}: {exc}")

            # Wiki pages
            wiki_rows = db.execute(_text("""
                SELECT wp.id, wp.title, wp.content_md
                FROM wiki_pages wp
                LEFT JOIN wiki_embeddings we ON we.page_id = wp.id
                WHERE wp.is_deleted = false AND we.page_id IS NULL
                LIMIT 500
            """)).fetchall()
            logger.info(f"Bulk embedding {len(wiki_rows)} un-indexed wiki pages…")
            for r in wiki_rows:
                try:
                    await embed_and_store_wiki(str(r.id), r.title or "", r.content_md or "", db)
                except Exception as exc:
                    logger.warning(f"Auto-embed skipped for wiki page {r.id}: {exc}")

            logger.info("Bulk embedding complete")
        finally:
            db.close()
    except Exception as exc:
        logger.error(f"Bulk embed job failed: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Trackly API…")

    # Ensure all ORM models are registered with Base.metadata before create_all
    import app.models  # noqa: F401 — side-effect: registers all models

    # Create any tables that don't exist yet (idempotent; Alembic handles migrations)
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified")

    # Ensure pgvector extension + embedding columns on both embedding tables
    from sqlalchemy import text
    with engine.connect() as _conn:
        try:
            _conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            _conn.execute(text(
                "ALTER TABLE ticket_embeddings ADD COLUMN IF NOT EXISTS embedding vector(384)"
            ))
            _conn.execute(text(
                "ALTER TABLE wiki_embeddings ADD COLUMN IF NOT EXISTS embedding vector(384)"
            ))
            # Add label column to code_review_snapshots if it was created before this migration
            _conn.execute(text(
                "ALTER TABLE code_review_snapshots ADD COLUMN IF NOT EXISTS label VARCHAR(500)"
            ))
            _conn.commit()
            logger.info("pgvector extension and embedding columns verified")
        except Exception as _e:
            logger.warning(f"pgvector setup warning (non-fatal): {_e}")
            _conn.rollback()

    # Ensure upload directory exists
    import os
    os.makedirs(settings.upload_dir, exist_ok=True)

    # Start background scheduler
    from app.jobs.scheduler import start_scheduler
    start_scheduler()

    # Kick off a background task to embed any tickets that were synced before embeddings existed
    import asyncio
    asyncio.create_task(_bulk_embed_unindexed())

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
