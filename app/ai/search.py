"""
app/ai/search.py — Semantic search + RAG pipeline using pgvector.

NOTE: SQLAlchemy's :param syntax conflicts with PostgreSQL's ::cast syntax,
so all vector casts use CAST(:param AS vector) instead of :param::vector.
"""

import re
import logging
from sqlalchemy import text

from app.ai.nova import embed, rerank, chat
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

SEARCH_SYSTEM = """You are NOVA — the personal AI brain for this engineering project on Trackly.
You know the team's tickets, decisions, wiki, and standups.
Answer like a knowledgeable teammate: direct, specific, helpful.
Reference ticket keys (e.g. TRKLY-4) when relevant.
If information is available in context, use it. If not, say so briefly and suggest next steps."""


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


async def keyword_search_tickets(query: str, org_id: str, limit: int = 8) -> list[dict]:
    """Direct SQL keyword search — works immediately even before embeddings are indexed."""
    lower_q = query.lower()

    # --- Detect type intent from query ---
    want_bugs  = bool(re.search(r'\bbug[s]?\b|\berror[s]?\b|\bcrash\b|\bfail\b|\bissue[s]?\b', lower_q))
    want_tasks = bool(re.search(r'\btask[s]?\b|\bfeature[s]?\b|\bimplementation\b', lower_q))

    # --- Extract meaningful search terms ---
    stopwords = {
        "the","is","in","a","an","are","was","were","for","of","to","and","or","with",
        "there","any","related","about","that","this","which","what","where","when","how",
        "why","has","have","all","also","its","not","working","it","do","be","me","my",
        "we","our","give","show","find","check","get","some","all","please","can","will",
        # type words — handled via issue_type filter, not text search
        "bug","bugs","error","errors","issue","issues","task","tasks","ticket","tickets",
        "feature","features",
    }
    # Also drop project-key-like tokens (e.g. "trkly", "trk", "jira") — they match every ticket
    project_code_re = re.compile(r'^[a-z]{2,8}$')

    raw_terms = [t for t in re.split(r'\W+', lower_q) if len(t) > 2 and t not in stopwords]

    # Remove tokens that look like project codes (short alpha-only, all lowercase) unless clearly a real word
    real_words = {"login","logout","auth","payment","dashboard","profile","admin","user","session",
                  "token","signup","password","email","search","filter","report","export","import",
                  "sprint","kanban","ticket","wiki","space","deploy","build","test","staging","prod"}
    terms = [t for t in raw_terms if not project_code_re.match(t) or t in real_words]

    if not terms and not want_bugs and not want_tasks:
        return []

    db = SessionLocal()
    try:
        params: dict = {"org_id": org_id, "limit": limit}
        where_clauses = ["t.org_id = :org_id", "t.is_deleted = false"]

        # Issue type filter
        if want_bugs and not want_tasks:
            where_clauses.append("t.issue_type = 'Bug'")

        # Keyword filter — AND across all terms (precise match)
        if terms:
            for i, term in enumerate(terms):
                params[f"term_{i}"] = f"%{term}%"
            and_conditions = " AND ".join(
                f"LOWER(t.summary || ' ' || COALESCE(t.description, '')) LIKE :term_{i}"
                for i in range(len(terms))
            )
            where_clauses.append(f"({and_conditions})")

        where_sql = " AND ".join(where_clauses)

        rows = db.execute(text(f"""
            SELECT t.id::text as id, 'ticket' as source_type,
                   t.jira_key as key, t.summary as title,
                   t.issue_type, t.status, t.priority, t.pod,
                   COALESCE(SUBSTRING(t.description, 1, 300), '') as snippet,
                   0.7 as similarity
            FROM jira_tickets t
            WHERE {where_sql}
            ORDER BY
              CASE t.issue_type WHEN 'Bug' THEN 0 ELSE 1 END,
              CASE t.priority WHEN 'Highest' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END
            LIMIT :limit
        """), params).fetchall()

        results = [dict(r._mapping) for r in rows]

        # If strict AND+type filter found nothing, relax to OR across terms (keep type filter)
        if not results and terms:
            for i, term in enumerate(terms):
                params[f"term_{i}"] = f"%{term}%"
            or_conditions = " OR ".join(
                f"LOWER(t.summary || ' ' || COALESCE(t.description, '')) LIKE :term_{i}"
                for i in range(len(terms))
            )
            where_clauses_relaxed = [c for c in where_clauses if "LIKE" not in c]
            where_clauses_relaxed.append(f"({or_conditions})")
            where_sql_relaxed = " AND ".join(where_clauses_relaxed)
            rows = db.execute(text(f"""
                SELECT t.id::text as id, 'ticket' as source_type,
                       t.jira_key as key, t.summary as title,
                       t.issue_type, t.status, t.priority, t.pod,
                       COALESCE(SUBSTRING(t.description, 1, 300), '') as snippet,
                       0.7 as similarity
                FROM jira_tickets t
                WHERE {where_sql_relaxed}
                ORDER BY
                  CASE t.issue_type WHEN 'Bug' THEN 0 ELSE 1 END,
                  CASE t.priority WHEN 'Highest' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END
                LIMIT :limit
            """), params).fetchall()
            results = [dict(r._mapping) for r in rows]

        return results
    except Exception:
        return []
    finally:
        db.close()


async def nl_query(query: str, org_id: str, user_context: str = "") -> dict:
    semantic = await semantic_search(query, org_id, limit=5)
    good_semantic = [r for r in semantic if (r.get("similarity") or 0) >= 0.55]

    # Always try keyword search in parallel to supplement or replace semantic results
    keyword_results = await keyword_search_tickets(query, org_id, limit=8)

    # Merge: prefer good semantic, fill with keyword results not already included
    seen_keys = {r.get("key") for r in good_semantic}
    merged = list(good_semantic) + [r for r in keyword_results if r.get("key") not in seen_keys]
    results = merged[:8]

    # Build context docs
    contexts = []
    for r in results:
        if r.get("source_type") == "ticket":
            meta = f"{r.get('issue_type','?')} · {r.get('status','?')} · {r.get('priority','?')}"
            contexts.append(f"[TICKET] {r['key']} ({meta})\nTitle: {r['title']}\n{r.get('snippet','')}")
        else:
            contexts.append(f"[{r.get('source_type','doc').upper()}] {r.get('key','')} — {r['title']}\n{r.get('snippet','')}")

    system = SEARCH_SYSTEM
    if user_context:
        system += f"\n\n## Live project context\n{user_context}"

    if results:
        answer = await chat(
            user_message=f"Question: {query}",
            system_prompt=system,
            context_docs=contexts,
            temperature=0.1,
        )
    else:
        answer = await chat(
            user_message=query,
            system_prompt=(
                system + "\n\nNo matching tickets or wiki pages found for this query. "
                "Answer using the project context above if relevant, otherwise use general engineering knowledge."
            ),
            temperature=0.2,
        )

    return {"answer": answer, "sources": results}


async def find_similar_tickets(
    embedding: list[float],
    org_id: str,
    threshold: float = 0.72,
    limit: int = 3,
    query_text: str = "",
) -> list[dict]:
    db  = SessionLocal()
    emb = str(embedding)
    try:
        # Vector similarity search
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
        results = [dict(r._mapping) for r in rows]

        if results:
            logger.info(f"find_similar_tickets: vector search found {len(results)} results (top similarity: {results[0].get('similarity', '?'):.3f})")
            return results

        # Log top scores even when below threshold (helps tune the threshold)
        try:
            top = db.execute(text("""
                SELECT t.summary, 1 - (te.embedding <=> CAST(:emb AS vector)) as similarity
                FROM ticket_embeddings te
                JOIN jira_tickets t ON te.ticket_id = t.id
                WHERE t.org_id = :org_id AND t.status != 'Done'
                ORDER BY te.embedding <=> CAST(:emb AS vector) LIMIT 3
            """), {"emb": emb, "org_id": org_id}).fetchall()
            for r in top:
                logger.info(f"find_similar_tickets: below-threshold candidate '{r.summary}' similarity={r.similarity:.3f}")
        except Exception:
            pass

        # Keyword fallback — catches obvious title overlaps that fall below embedding threshold
        if query_text:
            words = [w for w in re.sub(r"[^a-z0-9 ]", "", query_text.lower()).split() if len(w) >= 4][:6]
            if len(words) >= 2:
                like_clauses = " AND ".join(f"LOWER(t.summary) LIKE :w{i}" for i in range(len(words)))
                params: dict = {"org_id": org_id, "limit": limit}
                params.update({f"w{i}": f"%{w}%" for i, w in enumerate(words)})
                kw_rows = db.execute(text(f"""
                    SELECT t.jira_key, t.summary, t.status, 0.65 as similarity
                    FROM jira_tickets t
                    WHERE t.org_id = :org_id AND t.is_deleted = false AND t.status != 'Done'
                      AND {like_clauses}
                    LIMIT :limit
                """), params).fetchall()
                kw_results = [dict(r._mapping) for r in kw_rows]
                if kw_results:
                    logger.info(f"find_similar_tickets: keyword fallback found {len(kw_results)} results")
                return kw_results

        return []
    except Exception as e:
        logger.warning(f"find_similar_tickets failed: {e}")
        return []
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
