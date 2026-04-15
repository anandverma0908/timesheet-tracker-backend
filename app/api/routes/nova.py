"""
app/api/routes/nova.py — NOVA AI endpoints.

Endpoints:
  GET  /api/nova/status                  Check if Ollama is running + model loaded
  POST /api/nova/query                   NL query RAG — used by search modal
  POST /api/nova/sprint-retro/:id        Generate sprint retrospective markdown
  POST /api/nova/release-notes/:id       Generate release notes markdown
  POST /api/nova/standup/generate        Generate standup for a user
  GET  /api/nova/standup/today           Get own standup for today
  GET  /api/nova/standup/team            Get all team standups (manager+)
  PUT  /api/nova/standup/:id             Edit own standup
  GET  /api/nova/knowledge-gaps          List detected knowledge gaps (PM+)
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_manager_up
from app.core.config import settings
from app.models.user import User
from app.schemas.search import NovaQueryRequest, NovaQueryOut

router = APIRouter(prefix="/api/nova", tags=["nova"])


# ── Schemas ────────────────────────────────────────────────────────────────

class StandupGenerateRequest(BaseModel):
    user_id:       Optional[str]  = None   # admin/manager can generate for others
    standup_date:  Optional[str]  = None   # ISO date, defaults to today


class StandupUpdateRequest(BaseModel):
    yesterday: Optional[str] = None
    today:     Optional[str] = None
    blockers:  Optional[str] = None
    is_shared: Optional[bool] = None


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/status")
async def nova_status(user: User = Depends(get_current_user)):
    """Check if NOVA (Ollama) is available and which model is loaded."""
    from app.ai.nova import is_available
    available = is_available()
    return {
        "available":  available,
        "model":      settings.nova_model,
        "ollama_url": settings.nova_base_url,
        "status":     "online" if available else "offline",
    }


@router.post("/query", response_model=NovaQueryOut)
async def nova_query(
    body: NovaQueryRequest,
    user: User = Depends(get_current_user),
):
    """RAG-powered natural language query over tickets + wiki."""
    from app.ai.search import nl_query, semantic_search
    from app.ai.nova import chat

    try:
        if body.scope == "tickets":
            results  = await semantic_search(body.query, user.org_id, limit=5)
            results  = [r for r in results if r.get("source_type") == "ticket"]
            contexts = [f"[TICKET] {r['title']}\n{r['snippet']}" for r in results]
            answer   = await chat(
                user_message=f"Question: {body.query}\n\nAnswer based on the context provided:",
                context_docs=contexts,
                temperature=0.2,
            )
        else:
            data    = await nl_query(body.query, user.org_id)
            answer  = data["answer"]
            results = data["sources"]

        return NovaQueryOut(answer=answer, sources=results)
    except Exception as e:
        raise HTTPException(503, f"NOVA is unavailable: {e}")


@router.post("/sprint-retro/{sprint_id}")
async def generate_retro(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Generate a structured sprint retrospective markdown via NOVA."""
    from app.ai.documents import generate_sprint_retro

    result = await generate_sprint_retro(sprint_id, user.org_id, db)
    return {"sprint_id": sprint_id, "retro": result}


@router.post("/release-notes/{sprint_id}")
async def generate_release_notes(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Generate user-facing release notes markdown via NOVA."""
    from app.ai.documents import generate_release_notes

    result = await generate_release_notes(sprint_id, user.org_id, db)
    return {"sprint_id": sprint_id, "release_notes": result}


@router.post("/standup/generate")
async def generate_standup(
    body: StandupGenerateRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Generate a NOVA-powered standup for the current user (or another user for managers)."""
    from app.ai.documents import generate_standup as _gen

    # Managers can generate for other users; others only for themselves
    target_id = body.user_id or user.id
    if target_id != user.id and user.role not in ("admin", "engineering_manager"):
        raise HTTPException(403, "Only managers can generate standups for others")

    standup_date = body.standup_date or date.today().isoformat()

    try:
        result = await _gen(target_id, user.org_id, standup_date, db)
    except Exception as e:
        raise HTTPException(500, f"Standup generation failed: {e}")

    if "error" in result:
        raise HTTPException(404, result["error"])

    return result


@router.get("/standup/today")
async def get_my_standup(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Return the current user's standup for today, if it exists."""
    from app.models.sprint import Standup

    today = date.today()
    standup = db.query(Standup).filter(
        Standup.user_id == user.id,
        Standup.date    == today,
    ).first()

    if not standup:
        return {"message": "No standup for today yet. Use POST /api/nova/standup/generate."}

    return {
        "id":        standup.id,
        "user_id":   standup.user_id,
        "date":      standup.date.isoformat(),
        "yesterday": standup.yesterday,
        "today":     standup.today,
        "blockers":  standup.blockers,
        "is_shared": standup.is_shared,
    }


@router.get("/standup/team")
async def get_team_standups(
    standup_date: Optional[str] = Query(None, description="ISO date, defaults to today"),
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Return all team standups for a given date (managers and above)."""
    from app.models.sprint import Standup
    from app.models.user import User as UserModel

    target_date = date.fromisoformat(standup_date) if standup_date else date.today()

    standups = db.query(Standup).filter(
        Standup.org_id == user.org_id,
        Standup.date   == target_date,
    ).all()

    result = []
    for s in standups:
        member = db.query(UserModel).filter(UserModel.id == s.user_id).first()
        result.append({
            "id":             s.id,
            "user_id":        s.user_id,
            "engineer":       member.name if member else None,
            "engineer_email": member.email if member else None,
            "pod":            member.pod  if member else None,
            "date":           s.date.isoformat(),
            "yesterday":      s.yesterday,
            "today":          s.today,
            "blockers":       s.blockers,
            "shared":         s.is_shared,
        })

    return {"date": target_date.isoformat(), "standups": result}


@router.put("/standup/{standup_id}")
async def update_standup(
    standup_id: str,
    body: StandupUpdateRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Engineer edits their own standup (managers can edit any)."""
    from app.models.sprint import Standup

    standup = db.query(Standup).filter(Standup.id == standup_id).first()
    if not standup:
        raise HTTPException(404, "Standup not found")

    # Enforce ownership (unless manager/admin)
    if standup.user_id != user.id and user.role not in ("admin", "engineering_manager"):
        raise HTTPException(403, "You can only edit your own standup")

    if body.yesterday is not None:
        standup.yesterday = body.yesterday
    if body.today is not None:
        standup.today = body.today
    if body.blockers is not None:
        standup.blockers = body.blockers
    if body.is_shared is not None:
        standup.is_shared = body.is_shared

    db.commit()
    db.refresh(standup)

    return {
        "id":        standup.id,
        "user_id":   standup.user_id,
        "date":      standup.date.isoformat(),
        "yesterday": standup.yesterday,
        "today":     standup.today,
        "blockers":  standup.blockers,
        "is_shared": standup.is_shared,
    }


@router.get("/knowledge-gaps")
async def knowledge_gaps(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Return detected knowledge gaps for the org (latest run)."""
    from app.models.sprint import KnowledgeGap
    import json

    gaps = db.query(KnowledgeGap).filter(
        KnowledgeGap.org_id == user.org_id,
    ).order_by(KnowledgeGap.detected_at.desc()).limit(50).all()

    return [
        {
            "id":              g.id,
            "topic":           g.topic,
            "ticket_count":    g.ticket_count,
            "wiki_coverage":   g.wiki_coverage,
            "example_tickets": json.loads(g.example_tickets) if g.example_tickets else [],
            "suggestion":      g.suggestion,
            "detected_at":     g.detected_at.isoformat() if g.detected_at else None,
        }
        for g in gaps
    ]


@router.post("/knowledge-gaps/detect")
async def trigger_gap_detection(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Manually trigger knowledge gap detection for the org."""
    from app.ai.knowledge_gaps import detect_knowledge_gaps

    gaps = await detect_knowledge_gaps(user.org_id, db)
    return {"detected": len(gaps), "gaps": gaps}
