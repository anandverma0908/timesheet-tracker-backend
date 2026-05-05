"""
app/ai/search.py — Semantic search + RAG pipeline using pgvector.

NOTE: SQLAlchemy's :param syntax conflicts with PostgreSQL's ::cast syntax,
so all vector casts use CAST(:param AS vector) instead of :param::vector.
"""

import re
import json
import logging
from typing import Optional
from sqlalchemy import text

from app.ai.nova import embed, rerank, chat
from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

SEARCH_SYSTEM = """You are EOS — the AI assistant inside Trackly, a project management platform.

SCOPE: You ONLY answer questions about this team's Trackly workspace — tickets, sprints, wiki, decisions, standups, timesheets, goals, team members. You do not answer general questions unrelated to this project.

Rules:
- Answer ONLY from the provided context documents shown below.
- Reference ticket keys (e.g. TRKLY-4) when present in the context.
- Never fabricate ticket keys, dates, names, or any data not explicitly in the context.
- If the context does not contain the answer, reply: "I couldn't find that in your workspace data."
- Do NOT use general engineering knowledge or training data to fill gaps.
- Lead with the key fact, then supporting detail. Be concise."""


SEMANTIC_THRESHOLD = 0.20  # minimum cosine similarity; all-MiniLM-L6-v2 scores are lower than intuition suggests

async def semantic_search(
    query: str,
    org_id: str,
    limit: int = 10,
    allowed_emails: Optional[set] = None,
    allowed_pods: Optional[set] = None,
) -> list[dict]:
    query_emb = str(embed(query))  # raises RuntimeError if sentence_transformers unavailable → 503

    # Build optional visibility filters — either emails OR pods qualify (OR logic, same as list_tickets)
    ticket_extra_sql = ""
    ticket_params: dict = {"emb": query_emb, "org_id": org_id, "limit": limit, "threshold": SEMANTIC_THRESHOLD}

    if allowed_emails is not None or allowed_pods is not None:
        clauses = []
        if allowed_emails:
            placeholders = ", ".join(f":em_{i}" for i, _ in enumerate(allowed_emails))
            clauses.append(f"t.assignee_email IN ({placeholders})")
            ticket_params.update({f"em_{i}": e for i, e in enumerate(allowed_emails)})
        if allowed_pods:
            placeholders = ", ".join(f":pod_{i}" for i, _ in enumerate(allowed_pods))
            clauses.append(f"t.pod IN ({placeholders})")
            ticket_params.update({f"pod_{i}": p for i, p in enumerate(allowed_pods)})
        if clauses:
            ticket_extra_sql = " AND (" + " OR ".join(clauses) + ")"

    db = SessionLocal()
    try:
        tickets = db.execute(text(f"""
            SELECT t.id::text as id, 'ticket' as source_type, t.jira_key as key, t.summary as title,
                   te.content_snippet as snippet,
                   1 - (te.embedding <=> CAST(:emb AS vector)) as similarity
            FROM ticket_embeddings te
            JOIN jira_tickets t ON te.ticket_id = t.id
            WHERE t.org_id = :org_id AND t.is_deleted = false
              AND 1 - (te.embedding <=> CAST(:emb AS vector)) >= :threshold
              {ticket_extra_sql}
            ORDER BY te.embedding <=> CAST(:emb AS vector) LIMIT :limit
        """), ticket_params).fetchall()

        try:
            wiki = db.execute(text("""
                SELECT wp.id::text as id, 'wiki' as source_type, wp.id::text as key, wp.title,
                       we.content_snippet as snippet,
                       1 - (we.embedding <=> CAST(:emb AS vector)) as similarity
                FROM wiki_embeddings we
                JOIN wiki_pages wp ON we.page_id = wp.id
                WHERE wp.org_id = :org_id AND wp.is_deleted = false
                  AND 1 - (we.embedding <=> CAST(:emb AS vector)) >= :threshold
                ORDER BY we.embedding <=> CAST(:emb AS vector) LIMIT :limit
            """), {"emb": query_emb, "org_id": org_id, "limit": limit, "threshold": SEMANTIC_THRESHOLD}).fetchall()
        except Exception:
            wiki = []

        all_results = [{**dict(r._mapping), "similarity": float(r.similarity)} for r in list(tickets) + list(wiki)]
    finally:
        db.close()

    if not all_results:
        return []

    snippets    = [r["snippet"] or r["title"] for r in all_results]
    top_indices = rerank(query, snippets, top_k=min(8, len(all_results)))
    return [all_results[i] for i in top_indices]


async def keyword_search_tickets(query: str, org_id: str, limit: int = 8, pod: Optional[str] = None) -> list[dict]:
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

        if pod:
            where_clauses.append("t.pod = :pod")
            params["pod"] = pod

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

        results = [{**dict(r._mapping), "similarity": float(r.similarity)} for r in rows]

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
            results = [{**dict(r._mapping), "similarity": float(r.similarity)} for r in rows]

        return results
    except Exception:
        return []
    finally:
        db.close()


async def nl_query(query: str, org_id: str, user_context: str = "", pod: Optional[str] = None) -> dict:
    allowed_pods = {pod} if pod else None
    try:
        semantic = await semantic_search(query, org_id, limit=5, allowed_pods=allowed_pods)
    except Exception:
        semantic = []
    good_semantic = [r for r in semantic if (r.get("similarity") or 0) >= 0.55]

    # Always try keyword search in parallel to supplement or replace semantic results
    keyword_results = await keyword_search_tickets(query, org_id, limit=8, pod=pod)

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
                system + "\n\nNo matching tickets, wiki pages, or documents were found for this query. "
                "Reply: \"I couldn't find anything about that in your workspace. "
                "Try rephrasing or check if the data exists in Trackly.\""
            ),
            temperature=0.1,
        )

    return {"answer": answer, "sources": results}


_DUPE_THRESHOLD_CERTAIN   = 0.65   # above this → confirmed duplicate
_DUPE_THRESHOLD_UNCERTAIN = 0.50   # 0.50–0.65 → send to LLM for confirmation
_DUPE_SIMILARITY_LOG_TABLE = "duplicate_similarity_log"


async def _llm_confirm_duplicates(query_text: str, candidates: list[dict]) -> list[dict]:
    """Ask LLM to confirm which candidates in the uncertain band are true duplicates."""
    from app.ai.nova import chat
    numbered = "\n".join(
        f"{i+1}. [{c['jira_key']}] {c['summary']} (status: {c['status']})"
        for i, c in enumerate(candidates)
    )
    prompt = f"""You are a duplicate ticket detector. Given a new ticket and a list of existing tickets, identify which existing tickets are true duplicates (same issue, same root cause).

New ticket:
{query_text}

Existing candidates:
{numbered}

Reply with ONLY a JSON array of the numbers that are true duplicates. Example: [1, 3]
If none are duplicates, reply: []"""
    try:
        raw = await chat(prompt, temperature=0, max_tokens=60)
        match = re.search(r"\[.*?\]", raw, re.DOTALL)
        if match:
            indices = json.loads(match.group(0))
            return [candidates[i - 1] for i in indices if isinstance(i, int) and 1 <= i <= len(candidates)]
    except Exception as e:
        logger.warning(f"LLM duplicate confirmation failed: {e}")
    return []


def _log_similarity_scores(org_id: str, query_text: str, candidates: list) -> None:
    """Persist similarity scores for threshold calibration."""
    try:
        db = SessionLocal()
        for row in candidates:
            db.execute(text("""
                INSERT INTO duplicate_similarity_log
                    (id, org_id, query_snippet, jira_key, similarity, created_at)
                VALUES
                    (gen_random_uuid(), :org_id, :query, :key, :sim, NOW())
                ON CONFLICT DO NOTHING
            """), {
                "org_id": org_id,
                "query":  query_text[:200],
                "key":    row.jira_key,
                "sim":    float(row.similarity),
            })
        db.commit()
        db.close()
    except Exception:
        pass  # log table may not exist yet — never block the main flow


async def find_similar_tickets(
    embedding: list[float],
    org_id: str,
    threshold: float = 0.50,   # lowered from 0.58 — LLM filters false positives
    limit: int = 3,
    query_text: str = "",
) -> list[dict]:
    db  = SessionLocal()
    emb = str(embedding)
    try:
        count = db.execute(text("""
            SELECT COUNT(*) FROM ticket_embeddings te
            JOIN jira_tickets t ON te.ticket_id = t.id
            WHERE t.org_id = :org_id AND t.status != 'Done'
        """), {"org_id": org_id}).scalar()

        if count and count > 0:
            # Fetch candidates at the lower threshold (wider net)
            rows = db.execute(text("""
                SELECT t.jira_key, t.summary, t.status,
                       1 - (te.embedding <=> CAST(:emb AS vector)) as similarity
                FROM ticket_embeddings te
                JOIN jira_tickets t ON te.ticket_id = t.id
                WHERE t.org_id = :org_id
                  AND t.status != 'Done'
                  AND 1 - (te.embedding <=> CAST(:emb AS vector)) >= :threshold
                ORDER BY te.embedding <=> CAST(:emb AS vector) LIMIT :limit
            """), {"emb": emb, "org_id": org_id, "threshold": threshold, "limit": limit * 3}).fetchall()

            # Always log top candidates for calibration
            try:
                top_all = db.execute(text("""
                    SELECT t.jira_key, t.summary, 1 - (te.embedding <=> CAST(:emb AS vector)) as similarity
                    FROM ticket_embeddings te
                    JOIN jira_tickets t ON te.ticket_id = t.id
                    WHERE t.org_id = :org_id AND t.status != 'Done'
                    ORDER BY te.embedding <=> CAST(:emb AS vector) LIMIT 5
                """), {"emb": emb, "org_id": org_id}).fetchall()
                for r in top_all:
                    logger.info(f"[similarity] '{r.summary[:60]}' score={r.similarity:.4f}")
                _log_similarity_scores(org_id, query_text, top_all)
            except Exception:
                pass

            if rows:
                rows_dicts = [{**dict(r._mapping), "similarity": float(r.similarity)} for r in rows]
                certain   = [r for r in rows_dicts if r["similarity"] >= _DUPE_THRESHOLD_CERTAIN]
                uncertain = [r for r in rows_dicts if _DUPE_THRESHOLD_UNCERTAIN <= r["similarity"] < _DUPE_THRESHOLD_CERTAIN]

                logger.info(f"[duplicacy] certain={len(certain)} uncertain={len(uncertain)}")

                # Confirmed high-confidence duplicates pass through directly
                confirmed = list(certain)

                # Uncertain band → LLM decides
                if uncertain and query_text:
                    llm_confirmed = await _llm_confirm_duplicates(query_text, uncertain)
                    confirmed.extend(llm_confirmed)

                if confirmed:
                    return confirmed[:limit]

        # Fallback: keyword search
        if query_text:
            logger.info("find_similar_tickets: falling back to keyword search")
            keyword_results = await keyword_search_tickets(query_text, org_id, limit=limit)
            return [
                {
                    "jira_key":  r.get("key"),
                    "summary":   r.get("title"),
                    "status":    r.get("status", "Unknown"),
                    "similarity": r.get("similarity", 0.5),
                }
                for r in keyword_results if r.get("key")
            ]

        return []
    except Exception as e:
        logger.warning(f"find_similar_tickets failed: {e}")
        return []
    finally:
        db.close()


def _build_ticket_content(title: str, description: str, issue_type: str = "", pod: str = "") -> str:
    """Build the text that gets embedded — richer context = more accurate similarity."""
    parts = []
    if issue_type:
        parts.append(f"Type: {issue_type}")
    if pod:
        parts.append(f"Pod: {pod}")
    parts.append(f"Title: {title}")
    if description:
        parts.append(f"Description: {description}")
    return "\n".join(parts)


async def embed_and_store_ticket(
    ticket_id: str,
    title: str,
    description: str,
    db,
    issue_type: str = "",
    pod: str = "",
) -> None:
    from app.ai.nova import embed as nova_embed
    content   = _build_ticket_content(title, description, issue_type, pod)
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
