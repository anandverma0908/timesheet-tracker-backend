"""
app/core/dependencies.py — Reusable FastAPI dependency injectors.

Import these in every route that needs auth or a DB session.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

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
