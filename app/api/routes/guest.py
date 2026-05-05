"""
app/api/routes/guest.py — Guest / Client Portal API.

Endpoints:
  POST /api/guest/tokens           Create a guest access token (admin/manager)
  GET  /api/guest/tokens           List tokens for org
  DELETE /api/guest/tokens/{id}    Revoke (deactivate) a token
  GET  /api/guest/me               Validate token + return guest profile
  GET  /api/guest/tickets          List tickets visible to this guest
"""

import secrets
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_manager_up
from app.models.guest import GuestAccessToken
from app.models.ticket import JiraTicket

router = APIRouter(prefix="/api/guest", tags=["guest"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class TokenCreate(BaseModel):
    email:           str
    name:            str
    allowed_pods:    List[str]
    allowed_tickets: Optional[List[str]] = None
    expires_at:      Optional[datetime] = None


class TokenOut(BaseModel):
    id:              str
    token:           str
    email:           str
    name:            str
    allowed_pods:    Optional[list] = None
    allowed_tickets: Optional[list] = None
    expires_at:      Optional[datetime] = None
    is_active:       bool
    created_at:      datetime

    class Config:
        from_attributes = True


class GuestProfile(BaseModel):
    id:              str
    email:           str
    name:            str
    allowed_pods:    Optional[list] = None
    allowed_tickets: Optional[list] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _resolve_guest(
    db: Session,
    x_guest_token: Optional[str] = None,
) -> Optional[GuestAccessToken]:
    if not x_guest_token:
        return None
    guest = db.query(GuestAccessToken).filter(
        GuestAccessToken.token == x_guest_token,
        GuestAccessToken.is_active == True,
    ).first()
    if not guest:
        return None
    if guest.expires_at and datetime.utcnow() > guest.expires_at:
        return None
    return guest


# ── Admin / Manager endpoints ─────────────────────────────────────────────────

@router.post("/tokens", response_model=TokenOut, status_code=201)
async def create_guest_token(
    body: TokenCreate,
    db:   Session = Depends(get_db),
    user = Depends(get_manager_up),
):
    """Create a new guest access token. Only admin or engineering_manager."""
    token_str = _generate_token()
    gat = GuestAccessToken(
        id=secrets.token_hex(16),
        org_id=user.org_id,
        token=token_str,
        email=body.email,
        name=body.name,
        allowed_pods=body.allowed_pods,
        allowed_tickets=body.allowed_tickets,
        expires_at=body.expires_at,
        is_active=True,
    )
    db.add(gat)
    db.commit()
    db.refresh(gat)
    return gat


@router.get("/tokens", response_model=List[TokenOut])
async def list_guest_tokens(
    db:   Session = Depends(get_db),
    user = Depends(get_manager_up),
):
    """List all guest access tokens for the current org."""
    tokens = db.query(GuestAccessToken).filter(
        GuestAccessToken.org_id == user.org_id,
    ).order_by(GuestAccessToken.created_at.desc()).all()
    return tokens


@router.delete("/tokens/{token_id}", status_code=204)
async def revoke_guest_token(
    token_id: str,
    db:       Session = Depends(get_db),
    user     = Depends(get_manager_up),
):
    """Revoke (deactivate) a guest access token."""
    gat = db.query(GuestAccessToken).filter(
        GuestAccessToken.id == token_id,
        GuestAccessToken.org_id == user.org_id,
    ).first()
    if not gat:
        raise HTTPException(404, "Token not found")
    gat.is_active = False
    db.commit()
    return None


# ── Guest-facing endpoints ────────────────────────────────────────────────────

@router.get("/me", response_model=GuestProfile)
async def guest_me(
    db:             Session = Depends(get_db),
    x_guest_token:  Optional[str] = Header(None, alias="X-Guest-Token"),
):
    """Validate guest token and return profile with allowed pods."""
    guest = _resolve_guest(db, x_guest_token)
    if not guest:
        raise HTTPException(401, "Invalid or expired guest token")
    return {
        "id": guest.id,
        "email": guest.email,
        "name": guest.name,
        "allowed_pods": guest.allowed_pods,
        "allowed_tickets": guest.allowed_tickets,
    }


@router.get("/tickets")
async def guest_tickets(
    db:             Session = Depends(get_db),
    x_guest_token:  Optional[str] = Header(None, alias="X-Guest-Token"),
    limit:          int = Query(50, le=1000),
    offset:         int = Query(0),
):
    """List tickets visible to this guest (filtered by allowed_pods / allowed_tickets)."""
    guest = _resolve_guest(db, x_guest_token)
    if not guest:
        raise HTTPException(401, "Invalid or expired guest token")

    q = db.query(JiraTicket).filter(
        JiraTicket.org_id == guest.org_id,
        JiraTicket.is_deleted == False,
    )

    # Filter by allowed pods
    if guest.allowed_pods:
        q = q.filter(JiraTicket.pod.in_(guest.allowed_pods))

    # If specific tickets are allowed, further restrict
    if guest.allowed_tickets:
        q = q.filter(JiraTicket.jira_key.in_(guest.allowed_tickets))

    total = q.count()
    tickets = q.order_by(JiraTicket.synced_at.desc()).offset(offset).limit(limit).all()

    # Build lightweight output matching Ticket shape used by frontend
    def _to_out(t: JiraTicket) -> dict:
        return {
            "id": t.id,
            "key": t.jira_key,
            "project_key": t.project_key,
            "project_name": t.project_name,
            "summary": t.summary,
            "description": t.description,
            "assignee": t.assignee,
            "assignee_email": t.assignee_email,
            "reporter": t.reporter,
            "status": t.status,
            "client": t.client,
            "pod": t.pod,
            "hours_spent": t.hours_spent or 0,
            "original_estimate_hours": t.original_estimate_hours or 0,
            "remaining_estimate_hours": t.remaining_estimate_hours or 0,
            "story_points": t.story_points,
            "labels": t.labels or [],
            "issue_type": t.issue_type,
            "priority": t.priority,
            "url": t.url,
            "created": t.jira_created.isoformat() if t.jira_created else None,
            "updated": t.jira_updated.isoformat() if t.jira_updated else None,
            "worklogs": [],
        }

    return {
        "tickets": [_to_out(t) for t in tickets],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
