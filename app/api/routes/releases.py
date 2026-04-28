"""
app/api/routes/releases.py — Release / Version management.

Endpoints:
  GET    /api/spaces/{pod}/releases
  POST   /api/spaces/{pod}/releases
  PUT    /api/spaces/{pod}/releases/{id}
  DELETE /api/spaces/{pod}/releases/{id}
  POST   /api/tickets/{key}/fix-version
"""

from typing import Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.release import Release
from app.models.ticket import JiraTicket

router = APIRouter(prefix="/api/spaces", tags=["releases"])


class ReleaseCreatePayload(BaseModel):
    name: str
    description: Optional[str] = None
    release_date: Optional[str] = None


class ReleaseUpdatePayload(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    release_date: Optional[str] = None


class FixVersionPayload(BaseModel):
    version_name: Optional[str] = None


@router.get("/{pod}/releases")
async def list_releases(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    releases = db.query(Release).filter(
        Release.org_id == user.org_id,
        Release.pod == pod,
    ).order_by(Release.created_at.desc()).all()

    # Single aggregation query instead of N+1 per-release count
    count_rows = db.query(
        JiraTicket.fix_version,
        func.count(JiraTicket.id).label("cnt"),
    ).filter(
        JiraTicket.org_id == user.org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
        JiraTicket.fix_version.isnot(None),
    ).group_by(JiraTicket.fix_version).all()
    count_map = {row.fix_version: row.cnt for row in count_rows}

    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "status": r.status,
            "release_date": r.release_date.isoformat() if r.release_date else None,
            "ticket_count": count_map.get(r.name, 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in releases
    ]


@router.post("/{pod}/releases", status_code=201)
async def create_release(
    pod: str,
    payload: ReleaseCreatePayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.base import gen_uuid
    if db.query(Release).filter(
        Release.org_id == user.org_id,
        Release.pod == pod,
        Release.name == payload.name,
    ).first():
        raise HTTPException(409, f"A release named '{payload.name}' already exists in this pod")

    r = Release(
        id=gen_uuid(),
        org_id=user.org_id,
        pod=pod,
        name=payload.name,
        description=payload.description,
        release_date=date.fromisoformat(payload.release_date) if payload.release_date else None,
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "status": r.status,
        "release_date": r.release_date.isoformat() if r.release_date else None,
        "ticket_count": 0,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.put("/{pod}/releases/{release_id}")
async def update_release(
    pod: str,
    release_id: str,
    payload: ReleaseUpdatePayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    r = db.query(Release).filter(
        Release.id == release_id,
        Release.org_id == user.org_id,
        Release.pod == pod,
    ).first()
    if not r:
        raise HTTPException(404, "Release not found")

    if payload.name is not None:
        old_name = r.name
        r.name = payload.name
        # Update fix_version on tickets if name changed
        if old_name != payload.name:
            db.query(JiraTicket).filter(
                JiraTicket.org_id == user.org_id,
                JiraTicket.pod == pod,
                JiraTicket.fix_version == old_name,
            ).update({"fix_version": payload.name}, synchronize_session=False)

    if payload.description is not None:
        r.description = payload.description
    if payload.status is not None:
        r.status = payload.status
        if payload.status == "released" and not r.release_date:
            r.release_date = date.today()
    if payload.release_date is not None:
        r.release_date = date.fromisoformat(payload.release_date) if payload.release_date else None

    db.commit()
    db.refresh(r)
    ticket_count = db.query(JiraTicket).filter(
        JiraTicket.org_id == user.org_id,
        JiraTicket.pod == pod,
        JiraTicket.fix_version == r.name,
        JiraTicket.is_deleted == False,
    ).count()
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "status": r.status,
        "release_date": r.release_date.isoformat() if r.release_date else None,
        "ticket_count": ticket_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.delete("/{pod}/releases/{release_id}", status_code=204)
async def delete_release(
    pod: str,
    release_id: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    r = db.query(Release).filter(
        Release.id == release_id,
        Release.org_id == user.org_id,
        Release.pod == pod,
    ).first()
    if not r:
        raise HTTPException(404, "Release not found")

    db.query(JiraTicket).filter(
        JiraTicket.org_id == user.org_id,
        JiraTicket.pod == pod,
        JiraTicket.fix_version == r.name,
        JiraTicket.is_deleted == False,
    ).update({"fix_version": None}, synchronize_session=False)

    db.delete(r)
    db.commit()


@router.get("/{pod}/releases/{release_id}/tickets")
async def list_release_tickets(
    pod: str,
    release_id: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    r = db.query(Release).filter(
        Release.id == release_id,
        Release.org_id == user.org_id,
        Release.pod == pod,
    ).first()
    if not r:
        raise HTTPException(404, "Release not found")

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == user.org_id,
        JiraTicket.pod == pod,
        JiraTicket.fix_version == r.name,
        JiraTicket.is_deleted == False,
    ).order_by(JiraTicket.jira_key).all()

    return [
        {
            "id": t.id,
            "key": t.jira_key,
            "summary": t.summary,
            "status": t.status,
            "priority": t.priority,
            "issue_type": t.issue_type,
            "assignee": t.assignee,
            "assignee_email": t.assignee_email,
            "story_points": t.story_points,
            "url": t.url,
        }
        for t in tickets
    ]


@router.post("/tickets/{key}/fix-version")
async def set_fix_version(
    key: str,
    payload: FixVersionPayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    ticket = db.query(JiraTicket).filter(
        JiraTicket.jira_key == key,
        JiraTicket.org_id == user.org_id,
        JiraTicket.is_deleted == False,
    ).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    if payload.version_name:
        release = db.query(Release).filter(
            Release.name == payload.version_name,
            Release.org_id == user.org_id,
        ).first()
        if release and release.pod != ticket.pod:
            raise HTTPException(400, "Ticket pod does not match release pod")

    ticket.fix_version = payload.version_name
    db.commit()
    db.refresh(ticket)
    return {"key": key, "fix_version": ticket.fix_version}
