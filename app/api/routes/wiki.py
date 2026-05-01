"""
app/api/routes/wiki.py — Wiki spaces, pages, version history, related pages, AI meeting notes.

Endpoints:
  GET    /api/wiki/spaces              List spaces
  POST   /api/wiki/spaces              Create space (manager+)
  PUT    /api/wiki/spaces/:id          Update space (manager+)
  DELETE /api/wiki/spaces/:id          Delete space (admin)
  GET    /api/wiki/pages               List pages (?space_id=)
  POST   /api/wiki/pages               Create page — auto-embed
  GET    /api/wiki/pages/:id           Get page with content
  PUT    /api/wiki/pages/:id           Update — bump version, save version, re-embed
  DELETE /api/wiki/pages/:id           Soft delete (manager+)
  GET    /api/wiki/pages/:id/versions  Version history
  POST   /api/wiki/pages/:id/restore   Restore a version (manager+)
  GET    /api/wiki/pages/:id/related   Top 5 similar pages (pgvector)
  POST   /api/wiki/ai/meeting-notes    Extract action items from raw notes
"""

import json
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.dependencies import get_current_user, get_admin, get_manager_up, get_editor
from app.models.wiki import WikiSpace, WikiPage, WikiVersion
from app.models.user import User
from app.models.base import gen_uuid
from app.schemas.wiki import (
    WikiSpaceCreate, WikiSpaceUpdate, WikiSpaceOut,
    WikiPageCreate, WikiPageUpdate, WikiPageOut,
    WikiVersionOut, MeetingNotesRequest, MeetingNotesOut,
)

router = APIRouter(prefix="/api/wiki", tags=["wiki"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _page_to_out(page: WikiPage, db: Session) -> WikiPageOut:
    author_name = None
    if page.author_id:
        u = db.query(User).filter(User.id == page.author_id).first()
        author_name = u.name if u else None
    return WikiPageOut(
        id=page.id, space_id=page.space_id, org_id=page.org_id,
        parent_id=page.parent_id, title=page.title,
        content_md=page.content_md, content_html=page.content_html,
        version=page.version, author_id=page.author_id,
        author_name=author_name, is_deleted=page.is_deleted,
        created_at=page.created_at, updated_at=page.updated_at,
    )


async def _embed_wiki_bg(page_id: str, title: str, content_md: str):
    import logging
    try:
        from app.ai.search import embed_and_store_wiki
        db = SessionLocal()
        await embed_and_store_wiki(page_id, title, content_md or "", db)
        db.close()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Wiki embed failed for {page_id}: {e}")


_TICKET_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
_SECRET_PATTERNS = [
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|PRIVATE KEY)-----"),
]


def _page_text(page: WikiPage) -> str:
    return (page.content_md or page.content_html or "").strip()


def _freshness_metrics(page: WikiPage) -> tuple[int, str, int]:
    updated = page.updated_at
    if not updated:
        return 999, "stale", 15
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    days_old = max(0, (now - updated.replace(tzinfo=None)).days)
    if days_old <= 30:
        return days_old, "fresh", max(65, 100 - days_old)
    if days_old <= 75:
        return days_old, "aging", max(40, 82 - (days_old - 30))
    return days_old, "stale", max(15, 52 - (days_old - 75))


def _coverage_metrics(text: str) -> dict:
    headings = len(re.findall(r"^\s{0,3}#{1,6}\s+\S+", text, re.MULTILINE))
    examples = len(re.findall(r"```|^\s*[-*]\s|^\s*\d+\.\s", text, re.MULTILINE))
    links = len(re.findall(r"\[.+?\]\(.+?\)|https?://\S+", text))
    diagrams = len(re.findall(r"```(?:mermaid|graphviz)|!\[.*?\]\(.+?\)", text, re.IGNORECASE))

    heading_pct = min(100, 25 + headings * 18) if text else 0
    examples_pct = min(100, examples * 20)
    links_pct = min(100, links * 18)
    diagrams_pct = min(100, diagrams * 34)

    return {
        "headings": heading_pct,
        "examples": examples_pct,
        "links": links_pct,
        "diagrams": diagrams_pct,
    }


def _compliance_metrics(text: str) -> dict:
    matches = []
    for pattern in _SECRET_PATTERNS:
        hit = pattern.search(text)
        if hit:
            matches.append(hit.group(0)[:16])
    return {
        "passed": len(matches) == 0,
        "matches": matches[:3],
    }


def _page_health_from_related(page: WikiPage, related_rows: list[dict]) -> dict:
    text = _page_text(page)
    days_old, freshness, freshness_score = _freshness_metrics(page)
    coverage = _coverage_metrics(text)
    linked_tickets = len(set(_TICKET_KEY_RE.findall(text)))
    related_count = len(related_rows)
    best_similarity = max((float(r.get("similarity", 0) or 0) for r in related_rows), default=0.0)
    has_conflict = best_similarity > 0.9 and len(re.findall(r"\b\d+\s*(?:min|mins|minutes|hours|days)\b", text, re.IGNORECASE)) > 0

    score = round(
        freshness_score * 0.4
        + coverage["headings"] * 0.15
        + coverage["examples"] * 0.15
        + coverage["links"] * 0.15
        + coverage["diagrams"] * 0.1
        + min(100, related_count * 18) * 0.05
    )
    score = max(15, min(100, score))

    return {
        "days_old": days_old,
        "freshness": freshness,
        "score": score,
        "linked_tickets": linked_tickets,
        "related_count": related_count,
        "has_conflict": has_conflict,
        "coverage": coverage,
        "compliance": _compliance_metrics(text),
        "word_count": len(text.split()),
    }


def _related_pages_for(db: Session, page_id: str, org_id: str, limit: int = 5) -> list[dict]:
    try:
        rows = db.execute(text("""
            SELECT wp.id, wp.title, wp.space_id,
                   1 - (we.embedding <=> (
                       SELECT embedding FROM wiki_embeddings WHERE page_id = :pid
                   )) AS similarity
            FROM wiki_embeddings we
            JOIN wiki_pages wp ON we.page_id = wp.id
            WHERE wp.org_id  = :org_id
              AND wp.id      != :pid
              AND wp.is_deleted = false
            ORDER BY similarity DESC
            LIMIT :limit
        """), {"pid": page_id, "org_id": org_id, "limit": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def _space_health(space: WikiSpace, pages: list[WikiPage], related_by_page: dict[str, list[dict]]) -> dict:
    if not pages:
        return {
            "space_id": space.id,
            "health": 25,
            "page_count": 0,
            "fresh_count": 0,
            "aging_count": 0,
            "stale_count": 0,
        }

    page_metrics = [_page_health_from_related(page, related_by_page.get(page.id, [])) for page in pages]
    avg_score = round(sum(m["score"] for m in page_metrics) / len(page_metrics))
    return {
        "space_id": space.id,
        "health": avg_score,
        "page_count": len(pages),
        "fresh_count": sum(1 for m in page_metrics if m["freshness"] == "fresh"),
        "aging_count": sum(1 for m in page_metrics if m["freshness"] == "aging"),
        "stale_count": sum(1 for m in page_metrics if m["freshness"] == "stale"),
    }


def _onboarding_path(pages: list[WikiPage], related_by_page: dict[str, list[dict]]) -> list[dict]:
    ranked = []
    tags = ["Start here", "Core concepts", "Architecture", "Reference", "Advanced"]
    for page in pages:
        metrics = _page_health_from_related(page, related_by_page.get(page.id, []))
        rank = metrics["score"] + (12 if not page.parent_id else 0) + min(10, metrics["related_count"] * 2)
        ranked.append((rank, page, metrics))
    ranked.sort(key=lambda row: row[0], reverse=True)
    path = []
    for idx, (_, page, metrics) in enumerate(ranked[:5]):
        path.append({
            "page_id": page.id,
            "title": page.title,
            "minutes": max(8, min(30, 8 + metrics["word_count"] // 180)),
            "tag": tags[idx] if idx < len(tags) else "Reference",
            "freshness": metrics["freshness"],
            "score": metrics["score"],
        })
    return path


# ── SPACES ────────────────────────────────────────────────────────────────────

@router.get("/spaces", response_model=List[WikiSpaceOut])
async def list_spaces(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    spaces = db.query(WikiSpace).filter(WikiSpace.org_id == user.org_id).order_by(WikiSpace.name).all()
    return [WikiSpaceOut.model_validate(s) for s in spaces]


@router.post("/spaces", response_model=WikiSpaceOut, status_code=201)
async def create_space(
    body:    WikiSpaceCreate,
    db:      Session = Depends(get_db),
    manager: User    = Depends(get_manager_up),
):
    existing = db.query(WikiSpace).filter(
        WikiSpace.org_id == manager.org_id, WikiSpace.slug == body.slug
    ).first()
    if existing:
        raise HTTPException(409, f"Space with slug '{body.slug}' already exists")

    space = WikiSpace(
        id=gen_uuid(), org_id=manager.org_id,
        name=body.name, slug=body.slug,
        description=body.description,
        access_level=body.access_level or "private",
    )
    db.add(space)
    db.commit()
    db.refresh(space)
    return WikiSpaceOut.model_validate(space)


@router.put("/spaces/{space_id}", response_model=WikiSpaceOut)
async def update_space(
    space_id: str,
    body:     WikiSpaceUpdate,
    db:       Session = Depends(get_db),
    manager:  User    = Depends(get_manager_up),
):
    space = db.query(WikiSpace).filter(
        WikiSpace.id == space_id, WikiSpace.org_id == manager.org_id
    ).first()
    if not space:
        raise HTTPException(404, "Space not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(space, field, value)
    db.commit()
    db.refresh(space)
    return WikiSpaceOut.model_validate(space)


@router.delete("/spaces/{space_id}", status_code=204)
async def delete_space(
    space_id: str,
    db:       Session = Depends(get_db),
    admin:    User    = Depends(get_admin),
):
    space = db.query(WikiSpace).filter(
        WikiSpace.id == space_id, WikiSpace.org_id == admin.org_id
    ).first()
    if not space:
        raise HTTPException(404, "Space not found")
    db.delete(space)
    db.commit()


# ── PAGES ─────────────────────────────────────────────────────────────────────

@router.get("/pages", response_model=List[WikiPageOut])
async def list_pages(
    space_id: Optional[str] = Query(None),
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    q = db.query(WikiPage).filter(
        WikiPage.org_id == user.org_id,
        WikiPage.is_deleted == False,
    )
    if space_id:
        q = q.filter(WikiPage.space_id == space_id)
    pages = q.order_by(WikiPage.updated_at.desc()).all()
    return [_page_to_out(p, db) for p in pages]


@router.post("/pages", response_model=WikiPageOut, status_code=201)
async def create_page(
    body:             WikiPageCreate,
    background_tasks: BackgroundTasks,
    db:     Session = Depends(get_db),
    editor: User    = Depends(get_editor),
):
    space = db.query(WikiSpace).filter(
        WikiSpace.id == body.space_id, WikiSpace.org_id == editor.org_id
    ).first()
    if not space:
        raise HTTPException(404, "Space not found")

    page = WikiPage(
        id=gen_uuid(), space_id=body.space_id, org_id=editor.org_id,
        parent_id=body.parent_id, title=body.title,
        content_md=body.content_md, content_html=body.content_html,
        version=1, author_id=editor.id,
    )
    db.add(page)
    db.commit()
    db.refresh(page)

    background_tasks.add_task(_embed_wiki_bg, page.id, page.title, page.content_md or "")
    return _page_to_out(page, db)


@router.get("/pages/{page_id}", response_model=WikiPageOut)
async def get_page(
    page_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    page = db.query(WikiPage).filter(
        WikiPage.id == page_id,
        WikiPage.org_id == user.org_id,
        WikiPage.is_deleted == False,
    ).first()
    if not page:
        raise HTTPException(404, "Page not found")
    return _page_to_out(page, db)


@router.put("/pages/{page_id}", response_model=WikiPageOut)
async def update_page(
    page_id:          str,
    body:             WikiPageUpdate,
    background_tasks: BackgroundTasks,
    db:     Session = Depends(get_db),
    editor: User    = Depends(get_editor),
):
    page = db.query(WikiPage).filter(
        WikiPage.id == page_id,
        WikiPage.org_id == editor.org_id,
        WikiPage.is_deleted == False,
    ).first()
    if not page:
        raise HTTPException(404, "Page not found")

    # Archive current version before overwriting
    db.add(WikiVersion(
        id=gen_uuid(), page_id=page.id,
        version=page.version, content_md=page.content_md,
        author_id=editor.id,
    ))

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(page, field, value)
    page.version += 1
    db.commit()
    db.refresh(page)

    background_tasks.add_task(_embed_wiki_bg, page.id, page.title, page.content_md or "")
    return _page_to_out(page, db)


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(
    page_id: str,
    db:      Session = Depends(get_db),
    manager: User    = Depends(get_manager_up),
):
    page = db.query(WikiPage).filter(
        WikiPage.id == page_id,
        WikiPage.org_id == manager.org_id,
        WikiPage.is_deleted == False,
    ).first()
    if not page:
        raise HTTPException(404, "Page not found")
    page.is_deleted = True
    db.commit()


# ── VERSION HISTORY ───────────────────────────────────────────────────────────

@router.get("/pages/{page_id}/versions", response_model=List[WikiVersionOut])
async def list_versions(
    page_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    page = db.query(WikiPage).filter(
        WikiPage.id == page_id, WikiPage.org_id == user.org_id
    ).first()
    if not page:
        raise HTTPException(404, "Page not found")

    versions = db.query(WikiVersion).filter(
        WikiVersion.page_id == page_id
    ).order_by(WikiVersion.version.desc()).all()

    result = []
    for v in versions:
        author_name = None
        if v.author_id:
            u = db.query(User).filter(User.id == v.author_id).first()
            author_name = u.name if u else None
        result.append(WikiVersionOut(
            id=v.id, page_id=v.page_id, version=v.version,
            content_md=v.content_md, author_id=v.author_id,
            author_name=author_name, created_at=v.created_at,
        ))
    return result


@router.post("/pages/{page_id}/restore", response_model=WikiPageOut)
async def restore_version(
    page_id:          str,
    background_tasks: BackgroundTasks,
    version:          int     = Query(..., description="Version number to restore"),
    db:      Session = Depends(get_db),
    manager: User    = Depends(get_manager_up),
):
    page = db.query(WikiPage).filter(
        WikiPage.id == page_id, WikiPage.org_id == manager.org_id
    ).first()
    if not page:
        raise HTTPException(404, "Page not found")

    ver = db.query(WikiVersion).filter(
        WikiVersion.page_id == page_id, WikiVersion.version == version
    ).first()
    if not ver:
        raise HTTPException(404, f"Version {version} not found")

    # Archive current before restore
    db.add(WikiVersion(
        id=gen_uuid(), page_id=page.id,
        version=page.version, content_md=page.content_md,
        author_id=manager.id,
    ))

    from app.models.base import now as _now
    page.content_md = ver.content_md
    page.version   += 1
    page.updated_at = _now()
    db.commit()
    db.refresh(page)

    background_tasks.add_task(_embed_wiki_bg, page.id, page.title, page.content_md or "")
    return _page_to_out(page, db)


# ── RELATED PAGES ─────────────────────────────────────────────────────────────

@router.get("/pages/{page_id}/related", response_model=List[dict])
async def related_pages(
    page_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    page = db.query(WikiPage).filter(
        WikiPage.id == page_id, WikiPage.org_id == user.org_id
    ).first()
    if not page:
        raise HTTPException(404, "Page not found")

    return _related_pages_for(db, page_id, user.org_id, limit=5)


# ── WIKI INTELLIGENCE ────────────────────────────────────────────────────────

@router.get("/intelligence")
async def wiki_intelligence(
    space_id: Optional[str] = Query(None),
    page_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    spaces = db.query(WikiSpace).filter(WikiSpace.org_id == user.org_id).order_by(WikiSpace.name).all()
    pages_q = db.query(WikiPage).filter(
        WikiPage.org_id == user.org_id,
        WikiPage.is_deleted == False,
    )
    if space_id:
        pages_q = pages_q.filter(WikiPage.space_id == space_id)
    pages = pages_q.order_by(WikiPage.updated_at.desc()).all()

    related_by_page = {
        page.id: _related_pages_for(db, page.id, user.org_id, limit=5)
        for page in pages[:80]
    }

    space_health = []
    for space in spaces:
        space_pages = [page for page in pages if page.space_id == space.id] if space_id else [
            page for page in db.query(WikiPage).filter(
                WikiPage.org_id == user.org_id,
                WikiPage.space_id == space.id,
                WikiPage.is_deleted == False,
            ).all()
        ]
        local_related = {
            page.id: related_by_page.get(page.id, _related_pages_for(db, page.id, user.org_id, limit=5))
            for page in space_pages[:80]
        }
        space_health.append(_space_health(space, space_pages, local_related))

    page_health = None
    stale_pages = []
    page_metrics_rows = []
    if pages:
        for page in pages:
            metrics = _page_health_from_related(page, related_by_page.get(page.id, []))
            page_metrics_rows.append((page, metrics))
        stale_pages = [
            {
                "id": page.id,
                "title": page.title,
                "days_old": metrics["days_old"],
                "linked_tickets": metrics["linked_tickets"],
                "score": metrics["score"],
            }
            for page, metrics in page_metrics_rows
            if metrics["freshness"] == "stale"
        ][:5]

        if page_id:
            target = next((row for row in page_metrics_rows if row[0].id == page_id), None)
            if target:
                page, metrics = target
                page_health = {
                    **metrics,
                    "page_id": page.id,
                    "title": page.title,
                    "related_pages": related_by_page.get(page.id, []),
                }

    return {
        "spaces": space_health,
        "page_health": page_health,
        "stale_pages": stale_pages,
        "onboarding_path": _onboarding_path(pages, related_by_page) if pages else [],
        "map_stats": {
            "fresh": sum(1 for _, metrics in page_metrics_rows if metrics["freshness"] == "fresh"),
            "aging": sum(1 for _, metrics in page_metrics_rows if metrics["freshness"] == "aging"),
            "stale": sum(1 for _, metrics in page_metrics_rows if metrics["freshness"] == "stale"),
        },
    }


@router.post("/ai/assist")
async def wiki_assist(
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.ai.nova import chat
    from app.models.sprint import KnowledgeGap

    message = (body.get("message") or "").strip()
    page_id = body.get("page_id")
    space_id = body.get("space_id")
    if not message:
        raise HTTPException(400, "Message is required")

    page = None
    if page_id:
        page = db.query(WikiPage).filter(
            WikiPage.id == page_id,
            WikiPage.org_id == user.org_id,
            WikiPage.is_deleted == False,
        ).first()

    pages_q = db.query(WikiPage).filter(
        WikiPage.org_id == user.org_id,
        WikiPage.is_deleted == False,
    )
    if space_id:
        pages_q = pages_q.filter(WikiPage.space_id == space_id)
    scope_pages = pages_q.order_by(WikiPage.updated_at.desc()).limit(25).all()
    page_titles = "\n".join(f"- {p.title}" for p in scope_pages[:12])
    page_context = ""
    if page:
        related = _related_pages_for(db, page.id, user.org_id, limit=4)
        page_context = "\n".join([
            f"Active page title: {page.title}",
            f"Active page content:\n{_page_text(page)[:3000]}",
            "Related pages:",
            *[f"- {r['title']} ({round(float(r.get('similarity', 0) or 0) * 100)}% similar)" for r in related],
        ])

    knowledge_gaps = db.query(KnowledgeGap).filter(
        KnowledgeGap.org_id == user.org_id,
    ).order_by(KnowledgeGap.detected_at.desc()).limit(8).all()
    gaps_context = "\n".join(
        f"- {gap.topic}: {gap.wiki_coverage}% coverage, {gap.ticket_count} tickets"
        for gap in knowledge_gaps
    )

    prompt = "\n\n".join(part for part in [
        f"User request: {message}",
        f"Visible wiki pages:\n{page_titles}" if page_titles else "",
        page_context,
        f"Knowledge gaps:\n{gaps_context}" if gaps_context else "",
        "Answer specifically for the wiki workspace. Be concise and actionable. If asked for stale pages, conflicts, onboarding, or coverage gaps, use the provided wiki context and name concrete pages when possible.",
    ] if part)

    try:
        answer = await chat(prompt, temperature=0, max_tokens=500)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(503, f"Wiki assistant unavailable: {e}")


# ── AI MEETING NOTES ──────────────────────────────────────────────────────────

@router.post("/ai/meeting-notes", response_model=MeetingNotesOut)
async def extract_meeting_actions(
    body:   MeetingNotesRequest,
    editor: User = Depends(get_editor),
):
    from app.ai.nova import chat
    notes = (body.notes or body.content or "").strip()
    if not notes:
        raise HTTPException(400, "Notes are required")

    prompt = """Extract action items from these meeting notes.
Return ONLY valid JSON — no other text.

Meeting notes:
{notes}

Return JSON with this exact shape:
{{
  "action_items": [
    {{
      "action": "what needs to be done",
      "owner": "person responsible (or null)",
      "due": "due date as YYYY-MM-DD (or null)",
      "priority": "High|Medium|Low"
    }}
  ]
}}""".format(notes=notes)

    try:
        raw   = await chat(prompt, temperature=0, max_tokens=800)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        data  = json.loads(raw[start:end])
        actions = data.get("action_items", [])
        action_lines = "\n".join(
            f"- [ ] {item.get('action', 'Follow up')} ({item.get('priority', 'Medium')}"
            + (f" · {item.get('owner')}" if item.get("owner") else "")
            + (f" · due {item.get('due')}" if item.get("due") else "")
            + ")"
            for item in actions
        ) or "- [ ] Review notes and assign follow-ups"
        structured_md = "\n".join([
            "# Meeting Notes",
            "",
            f"> Structured by EOS · {datetime.now().strftime('%B %d, %Y')}",
            "",
            "## Raw Notes",
            "",
            notes[:3000],
            "",
            "## Action Items",
            "",
            action_lines,
        ])
        return MeetingNotesOut(action_items=actions, structured_md=structured_md)
    except Exception as e:
        raise HTTPException(422, f"NOVA could not parse meeting notes: {e}")


# ── Generative template ────────────────────────────────────────────────────────

TEMPLATE_PROMPTS = {
    "prd": (
        "Generate a comprehensive Product Requirements Document in Markdown for an engineering team. "
        "Include sections: Overview, Goals, Non-Goals, User Stories, Functional Requirements, "
        "Non-Functional Requirements, Success Metrics, and Open Questions. "
        "Use realistic placeholder content that shows the structure clearly. "
        "Context hint: {context}"
    ),
    "runbook": (
        "Generate a detailed operations Runbook in Markdown. "
        "Include sections: Purpose, Prerequisites, Scope, Step-by-Step Procedure (numbered), "
        "Expected Outputs, Rollback Steps, and Troubleshooting. "
        "Use realistic placeholder content. Context hint: {context}"
    ),
    "sprint_retro": (
        "Generate a Sprint Retrospective document in Markdown. "
        "Include sections: Sprint Summary, What Went Well, What to Improve, Root Cause Analysis, "
        "Action Items table (Action | Owner | Due | Status), and Team Health Check. "
        "Context hint: {context}"
    ),
    "meeting_notes": (
        "Generate a Meeting Notes template in Markdown with pre-filled structure. "
        "Include: Date/Time/Attendees header, Agenda, Discussion Points with sub-bullets, "
        "Decisions Made, Action Items table (Action | Owner | Due), and Next Steps. "
        "Context hint: {context}"
    ),
    "adr": (
        "Generate an Architecture Decision Record (ADR) in Markdown. "
        "Include sections: Title, Status, Date, Context and Problem Statement, "
        "Decision Drivers, Considered Options (with pros/cons table), Decision Outcome, "
        "Consequences (positive and negative), and Links. "
        "Context hint: {context}"
    ),
    "onboarding": (
        "Generate an Engineer Onboarding Guide in Markdown. "
        "Include sections: Welcome, Team Overview, Development Environment Setup (with code blocks), "
        "Key Systems & Tools, First Week Checklist, Coding Standards, Deployment Process, "
        "Who to Ask, and Resources. Context hint: {context}"
    ),
}


@router.post("/ai/generate-template")
async def generate_template(
    body: dict,
    editor: User = Depends(get_editor),
):
    """Use EOS to generate rich wiki page content for a given template type."""
    from app.ai.nova import chat

    template_type = (body.get("template_type") or "").lower().replace(" ", "_").replace("-", "_")
    context       = (body.get("context") or "").strip()[:500]

    prompt_template = TEMPLATE_PROMPTS.get(template_type)
    if not prompt_template:
        raise HTTPException(400, f"Unknown template type '{template_type}'. Valid: {list(TEMPLATE_PROMPTS)}")

    prompt = prompt_template.format(context=context or "general engineering team")

    try:
        content = await chat(
            prompt,
            system_prompt=(
                "You are EOS, an expert technical writer embedded in Trackly. "
                "Output clean, well-structured Markdown only — no preamble, no code fences around the whole document."
            ),
            temperature=0.4,
            max_tokens=1200,
        )
        return {"content": content.strip()}
    except Exception as e:
        raise HTTPException(503, f"EOS template generation failed: {e}")
