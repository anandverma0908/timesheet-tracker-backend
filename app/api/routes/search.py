"""
app/api/routes/search.py — Semantic search across tickets + wiki.

Endpoints:
  POST /api/search   Body: { query, scope: "all"|"tickets"|"wiki", limit? }
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user, get_visibility_scope, VisibilityScope
from app.models.user import User
from app.schemas.search import SearchRequest, SearchOut

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/debug", response_model=dict)
async def search_debug(user: User = Depends(get_current_user)):
    """Returns embedding index stats to diagnose search issues."""
    from sqlalchemy import text
    from app.core.database import SessionLocal
    from app.ai.nova import _ST_AVAILABLE, EMBEDDING_MODEL

    db = SessionLocal()
    try:
        ticket_count = db.execute(text(
            "SELECT COUNT(*) FROM ticket_embeddings te JOIN jira_tickets t ON te.ticket_id = t.id WHERE t.org_id = :org_id",
        ), {"org_id": user.org_id}).scalar()
        wiki_count = db.execute(text(
            "SELECT COUNT(*) FROM wiki_embeddings we JOIN wiki_pages wp ON we.page_id = wp.id WHERE wp.org_id = :org_id",
        ), {"org_id": user.org_id}).scalar()
        total_tickets = db.execute(text(
            "SELECT COUNT(*) FROM jira_tickets WHERE org_id = :org_id AND is_deleted = false",
        ), {"org_id": user.org_id}).scalar()

        # Sample similarity scores with a test query to check threshold tuning
        sample_scores = []
        if ticket_count and ticket_count > 0 and _ST_AVAILABLE:
            from app.ai.nova import embed
            test_emb = str(embed("test query"))
            rows = db.execute(text("""
                SELECT 1 - (te.embedding <=> CAST(:emb AS vector)) as similarity
                FROM ticket_embeddings te
                JOIN jira_tickets t ON te.ticket_id = t.id
                WHERE t.org_id = :org_id
                ORDER BY te.embedding <=> CAST(:emb AS vector) LIMIT 5
            """), {"emb": test_emb, "org_id": user.org_id}).fetchall()
            sample_scores = [round(float(r.similarity), 4) for r in rows]

    finally:
        db.close()

    return {
        "sentence_transformers_available": _ST_AVAILABLE,
        "embedding_model": str(EMBEDDING_MODEL) if EMBEDDING_MODEL else None,
        "indexed_tickets": ticket_count,
        "total_tickets": total_tickets,
        "indexed_wiki_pages": wiki_count,
        "sample_similarity_scores": sample_scores,
    }


@router.post("/reindex", response_model=dict)
async def reindex(user: User = Depends(get_current_user)):
    """Trigger background re-embedding for all un-indexed tickets and wiki pages in the org."""
    import asyncio
    from sqlalchemy import text
    from app.core.database import SessionLocal
    from app.ai.search import embed_and_store_ticket, embed_and_store_wiki

    async def _run():
        db = SessionLocal()
        try:
            # Tickets
            ticket_rows = db.execute(text("""
                SELECT t.id, t.summary, t.description
                FROM jira_tickets t
                LEFT JOIN ticket_embeddings te ON te.ticket_id = t.id
                WHERE t.org_id = :org_id AND t.is_deleted = false AND te.ticket_id IS NULL
                LIMIT 500
            """), {"org_id": user.org_id}).fetchall()
            for r in ticket_rows:
                try:
                    await embed_and_store_ticket(str(r.id), r.summary or "", r.description or "", db)
                except Exception:
                    pass

            # Wiki pages
            wiki_rows = db.execute(text("""
                SELECT wp.id, wp.title, wp.content_md
                FROM wiki_pages wp
                LEFT JOIN wiki_embeddings we ON we.page_id = wp.id
                WHERE wp.org_id = :org_id AND wp.is_deleted = false AND we.page_id IS NULL
                LIMIT 500
            """), {"org_id": user.org_id}).fetchall()
            for r in wiki_rows:
                try:
                    await embed_and_store_wiki(str(r.id), r.title or "", r.content_md or "", db)
                except Exception:
                    pass
        finally:
            db.close()

    asyncio.create_task(_run())
    return {"status": "reindex started"}


@router.post("", response_model=SearchOut)
async def search(
    body:  SearchRequest,
    user:  User            = Depends(get_current_user),
    scope: VisibilityScope = Depends(get_visibility_scope),
):
    """Semantic search over tickets + wiki using pgvector cosine similarity + reranking.
    Falls back to keyword search when embeddings are unavailable or return no results."""
    from app.ai.search import semantic_search, keyword_search_tickets

    results = []
    try:
        results = await semantic_search(
            query=body.query,
            org_id=user.org_id,
            limit=body.limit or 10,
            allowed_emails=scope.allowed_emails if not scope.unrestricted else None,
            allowed_pods=scope.allowed_pods if not scope.unrestricted else None,
        )
    except Exception:
        # Semantic search unavailable (e.g. embeddings not indexed, pgvector issue) —
        # fall through to keyword fallback below.
        pass

    # Fall back to keyword search if semantic returned nothing
    if not results and body.scope != "wiki":
        try:
            results = await keyword_search_tickets(body.query, user.org_id, limit=body.limit or 10)
        except Exception:
            pass

    if body.scope == "tickets":
        results = [r for r in results if r.get("source_type") == "ticket"]
    elif body.scope == "wiki":
        results = [r for r in results if r.get("source_type") == "wiki"]

    return SearchOut(results=results, query=body.query, scope=body.scope or "all")
