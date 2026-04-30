"""
app/api/routes/processes.py — SOP / Runbook / Workflow Process CRUD.

Endpoints:
  GET    /api/processes              List (filter by space_id, org_level, category)
  POST   /api/processes              Create
  GET    /api/processes/:id          Get single
  PUT    /api/processes/:id          Update
  DELETE /api/processes/:id          Soft-delete
  POST   /api/processes/:id/run      Increment run_count
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import date

from app.core.dependencies import get_current_user
from app.core.database import SessionLocal
from app.models.user import User

router = APIRouter(prefix="/api/processes", tags=["processes"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Schemas ───────────────────────────────────────────────────────────────────

class ProcessStepIn(BaseModel):
    id:             Optional[str] = None
    order:          int
    title:          str
    description:    Optional[str] = None
    owner:          Optional[str] = None
    estimatedTime:  Optional[str] = None
    required:       bool = True


class ProcessIn(BaseModel):
    title:               str
    category:            str = "workflow"
    status:              str = "active"
    owner:               Optional[str] = None
    lastUpdated:         Optional[str] = None
    description:         Optional[str] = None
    steps:               List[ProcessStepIn] = []
    tags:                List[str] = []
    complianceRequired:  bool = False
    avgCompletionTime:   Optional[str] = None
    space_id:            Optional[str] = None
    org_level:           bool = False


def _to_out(p) -> dict:
    steps = p.steps or []
    return {
        "id":                p.id,
        "title":             p.title,
        "category":          p.category,
        "status":            p.status,
        "owner":             p.owner,
        "lastUpdated":       p.last_updated,
        "description":       p.description,
        "steps":             steps,
        "tags":              p.tags or [],
        "complianceRequired": p.compliance_required,
        "avgCompletionTime": p.avg_completion_time,
        "runCount":          p.run_count or 0,
        "space_id":          p.space_id,
        "org_level":         p.org_level,
        "created_at":        p.created_at.isoformat() if p.created_at else "",
        "updated_at":        p.updated_at.isoformat() if p.updated_at else "",
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_processes(
    space_id:  Optional[str] = Query(None),
    org_level: Optional[bool] = Query(None),
    category:  Optional[str] = Query(None),
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Process
    q = db.query(Process).filter(
        Process.org_id == user.org_id,
        Process.is_deleted == False,
    )
    if space_id is not None:
        q = q.filter(Process.space_id == space_id)
    if org_level is not None:
        q = q.filter(Process.org_level == org_level)
    if category:
        q = q.filter(Process.category == category)
    processes = q.order_by(Process.created_at.desc()).all()
    return {"processes": [_to_out(p) for p in processes], "total": len(processes)}


@router.post("", response_model=dict, status_code=201)
async def create_process(
    body: ProcessIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Process
    from app.models.base import gen_uuid

    steps = [s.model_dump() for s in body.steps]
    # Ensure each step has an id
    for s in steps:
        if not s.get("id"):
            s["id"] = gen_uuid()

    p = Process(
        id=gen_uuid(),
        org_id=user.org_id,
        title=body.title,
        category=body.category,
        status=body.status,
        owner=body.owner,
        last_updated=body.lastUpdated or date.today().isoformat(),
        description=body.description,
        steps=steps,
        tags=body.tags,
        compliance_required=body.complianceRequired,
        avg_completion_time=body.avgCompletionTime,
        space_id=body.space_id,
        org_level=body.org_level,
        run_count=0,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.get("/{process_id}", response_model=dict)
async def get_process(
    process_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Process
    p = db.query(Process).filter(
        Process.id == process_id,
        Process.org_id == user.org_id,
        Process.is_deleted == False,
    ).first()
    if not p:
        raise HTTPException(404, "Process not found")
    return _to_out(p)


@router.put("/{process_id}", response_model=dict)
async def update_process(
    process_id: str,
    body: ProcessIn,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Process
    from app.models.base import gen_uuid
    p = db.query(Process).filter(
        Process.id == process_id,
        Process.org_id == user.org_id,
        Process.is_deleted == False,
    ).first()
    if not p:
        raise HTTPException(404, "Process not found")

    steps = [s.model_dump() for s in body.steps]
    for s in steps:
        if not s.get("id"):
            s["id"] = gen_uuid()

    p.title               = body.title
    p.category            = body.category
    p.status              = body.status
    p.owner               = body.owner
    p.last_updated        = body.lastUpdated or date.today().isoformat()
    p.description         = body.description
    p.steps               = steps
    p.tags                = body.tags
    p.compliance_required = body.complianceRequired
    p.avg_completion_time = body.avgCompletionTime
    p.space_id            = body.space_id
    p.org_level           = body.org_level
    db.commit()
    db.refresh(p)
    return _to_out(p)


@router.delete("/{process_id}", response_model=dict)
async def delete_process(
    process_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.knowledge import Process
    p = db.query(Process).filter(
        Process.id == process_id,
        Process.org_id == user.org_id,
        Process.is_deleted == False,
    ).first()
    if not p:
        raise HTTPException(404, "Process not found")
    p.is_deleted = True
    db.commit()
    return {"deleted": True}


@router.post("/{process_id}/run", response_model=dict)
async def run_process(
    process_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Increment run_count — called when a user marks a process as executed."""
    from app.models.knowledge import Process
    p = db.query(Process).filter(
        Process.id == process_id,
        Process.org_id == user.org_id,
        Process.is_deleted == False,
    ).first()
    if not p:
        raise HTTPException(404, "Process not found")
    p.run_count = (p.run_count or 0) + 1
    db.commit()
    return {"run_count": p.run_count}


@router.get("/compliance/dashboard", response_model=dict)
async def compliance_dashboard(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """
    Returns a compliance tracking dashboard with metrics across all compliance-required processes.
    """
    from app.models.knowledge import Process
    from sqlalchemy import func

    all_processes = db.query(Process).filter(
        Process.org_id == user.org_id,
        Process.is_deleted == False,
    ).all()

    compliance_processes = [p for p in all_processes if p.compliance_required]

    by_status: dict[str, int] = {}
    for p in compliance_processes:
        by_status[p.status] = by_status.get(p.status, 0) + 1

    total_runs = sum(p.run_count or 0 for p in compliance_processes)
    active_count = by_status.get("active", 0)
    review_count = by_status.get("review", 0)
    deprecated_count = by_status.get("deprecated", 0)
    draft_count = by_status.get("draft", 0)

    # Compliance score: active / (total non-deprecated) * 100
    eligible = active_count + review_count + draft_count
    compliance_score = round((active_count / eligible * 100) if eligible else 0)

    # At-risk: draft or in review (not fully active)
    at_risk = [_to_out(p) for p in compliance_processes if p.status in ("draft", "review")]
    # Active compliance processes, sorted by run_count desc (most used)
    active_items = sorted(
        [p for p in compliance_processes if p.status == "active"],
        key=lambda x: x.run_count or 0,
        reverse=True,
    )

    # Categories breakdown across all (not just compliance)
    category_counts: dict[str, int] = {}
    for p in all_processes:
        category_counts[p.category] = category_counts.get(p.category, 0) + 1

    return {
        "total_processes": len(all_processes),
        "compliance_required": len(compliance_processes),
        "compliance_score": compliance_score,
        "by_status": by_status,
        "total_runs": total_runs,
        "at_risk": at_risk,
        "active_items": [_to_out(p) for p in active_items[:10]],
        "category_breakdown": category_counts,
    }
