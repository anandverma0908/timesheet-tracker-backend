"""
app/ai/search.py — Semantic search + RAG pipeline using pgvector.

NOTE: SQLAlchemy's :param syntax conflicts with PostgreSQL's ::cast syntax,
so all vector casts use CAST(:param AS vector) instead of :param::vector.
"""

from sqlalchemy import text

from app.ai.nova import embed, rerank, chat
from app.core.database import SessionLocal

SEARCH_SYSTEM = """You are NOVA answering questions about Trackly work data.
Use ONLY the provided context. If the answer is not in context, say so.
Be concise. Cite sources by name."""


async def semantic_search(query: str, org_id: str, limit: int = 10) -> list[dict]:
    query_emb = str(embed(query))
    db = SessionLocal()
    try:
        tickets = db.execute(text("""
            SELECT t.id::text as id, 'ticket' as source_type, t.jira_key as key, t.summary as title,
                   te.content_snippet as snippet,
                   1 - (te.embedding <=> CAST(:emb AS vector)) as similarity
            FROM ticket_embeddings te
            JOIN jira_tickets t ON te.ticket_id = t.id
            WHERE t.org_id = :org_id AND t.is_deleted = false
            ORDER BY te.embedding <=> CAST(:emb AS vector) LIMIT :limit
        """), {"emb": query_emb, "org_id": org_id, "limit": limit}).fetchall()

        try:
            wiki = db.execute(text("""
                SELECT wp.id::text as id, 'wiki' as source_type, wp.id::text as key, wp.title,
                       we.content_snippet as snippet,
                       1 - (we.embedding <=> CAST(:emb AS vector)) as similarity
                FROM wiki_embeddings we
                JOIN wiki_pages wp ON we.page_id = wp.id
                WHERE wp.org_id = :org_id AND wp.is_deleted = false
                ORDER BY we.embedding <=> CAST(:emb AS vector) LIMIT :limit
            """), {"emb": query_emb, "org_id": org_id, "limit": limit}).fetchall()
        except Exception:
            wiki = []

        all_results = [dict(r._mapping) for r in list(tickets) + list(wiki)]
    finally:
        db.close()

    if not all_results:
        return []

    snippets    = [r["snippet"] or r["title"] for r in all_results]
    top_indices = rerank(query, snippets, top_k=min(8, len(all_results)))
    return [all_results[i] for i in top_indices]


async def nl_query(query: str, org_id: str) -> dict:
    results  = await semantic_search(query, org_id, limit=5)
    contexts = [f"[{r['source_type'].upper()}] {r['title']}\n{r['snippet']}" for r in results]
    answer   = await chat(
        user_message=f"Question: {query}\n\nAnswer based on the context provided:",
        context_docs=contexts,
        temperature=0.2,
    )
    return {"answer": answer, "sources": results}


async def find_similar_tickets(
    embedding: list[float],
    org_id: str,
    threshold: float = 0.85,
    limit: int = 3,
) -> list[dict]:
    db  = SessionLocal()
    emb = str(embedding)
    try:
        rows = db.execute(text("""
            SELECT t.jira_key, t.summary, t.status,
                   1 - (te.embedding <=> CAST(:emb AS vector)) as similarity
            FROM ticket_embeddings te
            JOIN jira_tickets t ON te.ticket_id = t.id
            WHERE t.org_id = :org_id
              AND t.status != 'Done'
              AND 1 - (te.embedding <=> CAST(:emb AS vector)) >= :threshold
            ORDER BY te.embedding <=> CAST(:emb AS vector) LIMIT :limit
        """), {"emb": emb, "org_id": org_id, "threshold": threshold, "limit": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    finally:
        db.close()


async def embed_and_store_ticket(ticket_id: str, title: str, description: str, db) -> None:
    from app.ai.nova import embed as nova_embed
    content   = f"{title}\n{description or ''}"
    embedding = str(nova_embed(content))
    db.execute(text("""
        INSERT INTO ticket_embeddings (id, ticket_id, embedding, content_snippet, updated_at)
        VALUES (gen_random_uuid(), :tid, CAST(:emb AS vector), :snippet, NOW())
        ON CONFLICT (ticket_id) DO UPDATE
        SET embedding = CAST(:emb AS vector), content_snippet = :snippet, updated_at = NOW()
    """), {"tid": ticket_id, "emb": embedding, "snippet": content[:500]})
    db.commit()


async def embed_and_store_wiki(page_id: str, title: str, content_md: str, db) -> None:
    from app.ai.nova import embed as nova_embed
    content   = f"{title}\n{content_md or ''}"
    embedding = str(nova_embed(content))
    db.execute(text("""
        INSERT INTO wiki_embeddings (id, page_id, embedding, content_snippet, updated_at)
        VALUES (gen_random_uuid(), :pid, CAST(:emb AS vector), :snippet, NOW())
        ON CONFLICT (page_id) DO UPDATE
        SET embedding = CAST(:emb AS vector), content_snippet = :snippet, updated_at = NOW()
    """), {"pid": page_id, "emb": embedding, "snippet": content[:500]})
    db.commit()
