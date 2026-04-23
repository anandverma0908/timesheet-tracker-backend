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

    page.content_md = ver.content_md
    page.version   += 1
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
            LIMIT 5
        """), {"pid": page_id, "org_id": user.org_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


# ── AI MEETING NOTES ──────────────────────────────────────────────────────────

@router.post("/ai/meeting-notes", response_model=MeetingNotesOut)
async def extract_meeting_actions(
    body:   MeetingNotesRequest,
    editor: User = Depends(get_editor),
):
    from app.ai.nova import chat

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
}}""".format(notes=body.notes)

    try:
        raw   = await chat(prompt, temperature=0, max_tokens=800)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        data  = json.loads(raw[start:end])
        return MeetingNotesOut(action_items=data.get("action_items", []))
    except Exception as e:
        raise HTTPException(422, f"NOVA could not parse meeting notes: {e}")
