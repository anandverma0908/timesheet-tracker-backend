"""
app/api/routes/search.py — Semantic search across tickets + wiki.

Endpoints:
  POST /api/search   Body: { query, scope: "all"|"tickets"|"wiki", limit? }
"""

from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.search import SearchRequest, SearchOut

router = APIRouter(prefix="/api/search", tags=["search"])


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
    body: SearchRequest,
    user: User = Depends(get_current_user),
):
    """Semantic search over tickets + wiki using pgvector cosine similarity + reranking."""
    from app.ai.search import semantic_search

    try:
        results = await semantic_search(
            query=body.query,
            org_id=user.org_id,
            limit=body.limit or 10,
        )

        if body.scope == "tickets":
            results = [r for r in results if r.get("source_type") == "ticket"]
        elif body.scope == "wiki":
            results = [r for r in results if r.get("source_type") == "wiki"]

        return SearchOut(results=results, query=body.query, scope=body.scope or "all")
    except Exception as e:
        raise HTTPException(503, f"Search unavailable: {e}")
