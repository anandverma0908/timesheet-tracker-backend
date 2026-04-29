"""
app/api/routes/goals.py — Goals / OKR management.

Endpoints:
  GET  /api/goals               List goals for org (optionally filtered by quarter)
  POST /api/goals               Create goal
  GET  /api/goals/:id           Get single goal
  PATCH /api/goals/:id          Update goal
  DELETE /api/goals/:id         Delete goal
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/goals", tags=["goals"])


# ── Schemas ────────────────────────────────────────────────────────────────

class KeyResultIn(BaseModel):
    id: str
    title: str
    current: float
    target: float
    unit: str
    linked_tickets: List[str] = []
    status: str = "on_track"


class GoalCreate(BaseModel):
    quarter: str
    title: str
    description: Optional[str] = None
    owner: Optional[str] = None
    status: str = "on_track"
    overall_progress: int = 0
    key_results: List[KeyResultIn] = []
    linked_sprints: List[str] = []


class GoalUpdate(BaseModel):
    quarter: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    status: Optional[str] = None
    overall_progress: Optional[int] = None
    key_results: Optional[List[KeyResultIn]] = None
    linked_sprints: Optional[List[str]] = None


class GoalOut(BaseModel):
    id: str
    quarter: str
    title: str
    description: Optional[str]
    owner: Optional[str]
    status: str
    overall_progress: int
    key_results: List[dict]
    linked_sprints: List[str]
    nova_insight: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]

    class Config:
        from_attributes = True


# ── Helpers ────────────────────────────────────────────────────────────────

def _goal_to_dict(goal) -> dict:
    return {
        "id": goal.id,
        "quarter": goal.quarter,
        "title": goal.title,
        "description": goal.description,
        "owner": goal.owner,
        "status": goal.status,
        "overall_progress": goal.overall_progress,
        "key_results": goal.key_results or [],
        "linked_sprints": goal.linked_sprints or [],
        "nova_insight": goal.nova_insight,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_goals(
    quarter: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.goal import Goal

    q = db.query(Goal).filter(Goal.org_id == user.org_id)
    if quarter:
        q = q.filter(Goal.quarter == quarter)

    goals = q.order_by(Goal.created_at.desc()).all()
    quarters = [
        row[0]
        for row in db.query(Goal.quarter)
        .filter(Goal.org_id == user.org_id)
        .distinct()
        .all()
    ]

    return {
        "goals": [_goal_to_dict(g) for g in goals],
        "quarters": sorted(quarters),
    }


@router.post("", status_code=201)
async def create_goal(
    body: GoalCreate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.goal import Goal
    from app.models.base import gen_uuid

    goal = Goal(
        id=gen_uuid(),
        org_id=user.org_id,
        quarter=body.quarter,
        title=body.title,
        description=body.description,
        owner=body.owner,
        status=body.status,
        overall_progress=body.overall_progress,
        key_results=[kr.model_dump() for kr in body.key_results],
        linked_sprints=body.linked_sprints,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return _goal_to_dict(goal)


@router.get("/{goal_id}")
async def get_goal(
    goal_id: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.goal import Goal

    goal = db.query(Goal).filter(
        Goal.id == goal_id,
        Goal.org_id == user.org_id,
    ).first()
    if not goal:
        raise HTTPException(404, "Goal not found")
    return _goal_to_dict(goal)


@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    body: GoalUpdate,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.goal import Goal

    goal = db.query(Goal).filter(
        Goal.id == goal_id,
        Goal.org_id == user.org_id,
    ).first()
    if not goal:
        raise HTTPException(404, "Goal not found")

    old_status = goal.status

    if body.quarter is not None:
        goal.quarter = body.quarter
    if body.title is not None:
        goal.title = body.title
    if body.description is not None:
        goal.description = body.description
    if body.owner is not None:
        goal.owner = body.owner
    if body.status is not None:
        goal.status = body.status
    if body.overall_progress is not None:
        goal.overall_progress = body.overall_progress
    if body.key_results is not None:
        goal.key_results = [kr.model_dump() for kr in body.key_results]
    if body.linked_sprints is not None:
        goal.linked_sprints = body.linked_sprints

    if body.status and body.status != old_status and body.status in ("at_risk", "behind"):
        from app.models.notification import Notification as Notif
        from app.models.base import gen_uuid
        from app.models.user import User
        label = "at risk" if body.status == "at_risk" else "behind schedule"
        owner_user = db.query(User).filter(
            User.org_id == user.org_id,
            User.name == goal.owner,
        ).first() if goal.owner else None
        if owner_user:
            db.add(Notif(
                id=gen_uuid(), org_id=user.org_id, user_id=owner_user.id,
                type="goal_status_changed",
                title=f"Goal is {label}: {goal.title[:60]}",
                body=f"Status changed from {old_status.replace('_', ' ')} to {label}.",
                link="/goals",
            ))

    db.commit()
    db.refresh(goal)
    return _goal_to_dict(goal)


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.goal import Goal

    goal = db.query(Goal).filter(
        Goal.id == goal_id,
        Goal.org_id == user.org_id,
    ).first()
    if not goal:
        raise HTTPException(404, "Goal not found")

    db.delete(goal)
    db.commit()
    return None
