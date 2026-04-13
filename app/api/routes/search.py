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
