"""
app/core/dependencies.py — Reusable FastAPI dependency injectors.

Import these in every route that needs auth or a DB session.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from fastapi import Depends, HTTPException, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.guest import GuestAccessToken

_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or user.status == "inactive":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def require_roles(*roles: str):
    """Factory: returns a dependency that enforces one of the given roles."""
    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(roles)}",
            )
        return user
    return _check


# Pre-built role guards — import these directly in routes
get_admin         = require_roles("admin")
get_manager_up    = require_roles("admin", "engineering_manager")
get_tech_lead_up  = require_roles("admin", "engineering_manager", "tech_lead")
get_editor        = require_roles("admin", "engineering_manager", "tech_lead", "team_member")


@dataclass
class VisibilityScope:
    """
    Resolved data-visibility rules for the current user.

    unrestricted    — True for admin; skip all filters
    allowed_pods    — None means no pod restriction; a set means only these pods
    allowed_emails  — None means no email restriction; a set means only these assignees
    """
    unrestricted:   bool            = False
    allowed_pods:   Optional[set]   = None
    allowed_emails: Optional[set]   = None


def get_visibility_scope(
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
) -> VisibilityScope:
    """
    Returns the visibility scope for the current user:
      admin                → unrestricted
      engineering_manager  → pods they're a space-member of + direct reports' tickets
      tech_lead            → their own pod only
      team_member          → only their own tickets (by email)
    """
    if user.role == "admin":
        return VisibilityScope(unrestricted=True)

    if user.role == "engineering_manager":
        from app.models.space_member import SpaceMember

        # Pods where this manager is explicitly assigned as a space member
        member_rows = db.query(SpaceMember).filter(
            SpaceMember.org_id == user.org_id,
            SpaceMember.user_id == user.id,
        ).all()
        manager_pods = {row.pod for row in member_rows}

        # Direct reports — users whose reporting_to == this manager's emp_no
        subordinate_emails: set = set()
        if user.emp_no:
            subordinates = db.query(User).filter(
                User.org_id == user.org_id,
                User.reporting_to == user.emp_no,
            ).all()
            subordinate_emails = {u.email for u in subordinates if u.email}

        # Manager can also see their own tickets
        subordinate_emails.add(user.email)

        return VisibilityScope(
            unrestricted=False,
            allowed_pods=manager_pods if manager_pods else None,
            allowed_emails=subordinate_emails if subordinate_emails else {user.email},
        )

    if user.role == "tech_lead":
        return VisibilityScope(
            unrestricted=False,
            allowed_pods={user.pod} if user.pod else None,
        )

    # team_member and any other roles — own tickets only
    return VisibilityScope(
        unrestricted=False,
        allowed_emails={user.email},
    )


# ── Guest dependency ──────────────────────────────────────────────────────────

def get_current_guest(
    x_guest_token: str = Header(..., alias="X-Guest-Token"),
    db: Session = Depends(get_db),
) -> GuestAccessToken:
    from datetime import datetime
    guest = db.query(GuestAccessToken).filter(
        GuestAccessToken.token == x_guest_token,
        GuestAccessToken.is_active == True,
    ).first()
    if not guest:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid guest token")
    if guest.expires_at and datetime.utcnow() > guest.expires_at:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Guest token expired")
    return guest
