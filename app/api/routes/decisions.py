"""
app/api/routes/decisions.py — ADR (Architecture Decision Record) CRUD.

Endpoints:
  GET    /api/decisions              List (filter by space_id, org_level, status)
  POST   /api/decisions              Create
  GET    /api/decisions/:id          Get single
  PUT    /api/decisions/:id          Update
  DELETE /api/decisions/:id          Soft-delete
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import date

from app.core.dependencies import get_current_user
from app.core.database import SessionLocal
from app.models.user import User

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Schemas ───────────────────────────────────────────────────────────────────

class DecisionIn(BaseModel):
    title:          str
    status:         str = "proposed"
    owner:          Optional[str] = None
    date:           Optional[str] = None
    context:        Optional[str] = None
    decision:       Optional[str] = None
    rationale:      Optional[str] = None
    alternatives:   List[str] = []
    consequences:   Optional[str] = None
    linked_tickets: List[str] = []
    tags:           List[str] = []
    space_id:       Optional[str] = None
    org_level:      bool = False


class DecisionOut(BaseModel):
    id:             str
    number:         int
    title:          str
    status:         str
    owner:          Optional[str]
    date:           Optional[str]
    context:        Optional[str]
    decision:       Optional[str]
    rationale:      Optional[str]
    alternatives:   List[str]
    consequences:   Optional[str]
    linkedTickets:  List[str]
    tags:           List[str]
    space_id:       Optional[str]
    org_level:      bool
    created_at:     str
    updated_at:     str

    class Config:
        from_attributes = True


def _to_out(d) -> dict:
    return {
        "id":            d.id,
        "number":        d.number,
        "title":         d.title,
        "status":        d.status,
        "owner":         d.owner,
        "date":          d.date,
        "context":       d.context,
        "decision":      d.decision,
        "rationale":     d.rationale,
        "alternatives":  d.alternatives or [],
        "consequences":  d.consequences,
        "linkedTickets": d.linked_tickets or [],
        "tags":          d.tags or [],
        "space_id":      d.space_id,
        "org_level":     d.org_level,
        "created_at":    d.created_at.isoformat() if d.created_at else "",
        "updated_at":    d.updated_at.isoformat() if d.updated_at else "",
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_decisions(
    space_id:  Optional[str] = Query(None),
    org_level: Optional[bool] = Query(None),
    status:    Optional[str] = Query(None),
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Decision
    q = db.query(Decision).filter(
        Decision.org_id == user.org_id,
        Decision.is_deleted == False,
    )
    if space_id is not None:
        q = q.filter(Decision.space_id == space_id)
    if org_level is not None:
        q = q.filter(Decision.org_level == org_level)
    if status:
        q = q.filter(Decision.status == status)
    decisions = q.order_by(Decision.number.desc()).all()
    return {"decisions": [_to_out(d) for d in decisions], "total": len(decisions)}


@router.post("", response_model=dict, status_code=201)
async def create_decision(
    body: DecisionIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Decision
    from app.models.base import gen_uuid

    # Auto-number within the org
    last = db.query(Decision).filter(
        Decision.org_id == user.org_id
    ).order_by(Decision.number.desc()).first()
    number = (last.number + 1) if last else 1

    d = Decision(
        id=gen_uuid(),
        org_id=user.org_id,
        number=number,
        title=body.title,
        status=body.status,
        owner=body.owner,
        date=body.date or date.today().isoformat(),
        context=body.context,
        decision=body.decision,
        rationale=body.rationale,
        alternatives=body.alternatives,
        consequences=body.consequences,
        linked_tickets=body.linked_tickets,
        tags=body.tags,
        space_id=body.space_id,
        org_level=body.org_level,
    )
    db.add(d)
    db.commit()
    db.refresh(d)
    return _to_out(d)


@router.get("/{decision_id}", response_model=dict)
async def get_decision(
    decision_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Decision
    d = db.query(Decision).filter(
        Decision.id == decision_id,
        Decision.org_id == user.org_id,
        Decision.is_deleted == False,
    ).first()
    if not d:
        raise HTTPException(404, "Decision not found")
    return _to_out(d)


@router.put("/{decision_id}", response_model=dict)
async def update_decision(
    decision_id: str,
    body: DecisionIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Decision
    d = db.query(Decision).filter(
        Decision.id == decision_id,
        Decision.org_id == user.org_id,
        Decision.is_deleted == False,
    ).first()
    if not d:
        raise HTTPException(404, "Decision not found")

    d.title         = body.title
    d.status        = body.status
    d.owner         = body.owner
    d.date          = body.date
    d.context       = body.context
    d.decision      = body.decision
    d.rationale     = body.rationale
    d.alternatives  = body.alternatives
    d.consequences  = body.consequences
    d.linked_tickets = body.linked_tickets
    d.tags          = body.tags
    d.space_id      = body.space_id
    d.org_level     = body.org_level
    db.commit()
    db.refresh(d)
    return _to_out(d)


@router.delete("/{decision_id}", response_model=dict)
async def delete_decision(
    decision_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Decision
    d = db.query(Decision).filter(
        Decision.id == decision_id,
        Decision.org_id == user.org_id,
        Decision.is_deleted == False,
    ).first()
    if not d:
        raise HTTPException(404, "Decision not found")
    d.is_deleted = True
    db.commit()
    return {"deleted": True}
