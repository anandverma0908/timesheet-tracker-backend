"""
app/api/routes/users.py — User management (admin only).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_admin
from app.core.security import hash_password
from app.models.user import User
from app.schemas.auth import UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[UserOut])
async def list_users(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_admin),
):
    users = db.query(User).filter(User.org_id == user.org_id).order_by(User.name).all()
    return [UserOut.model_validate(u) for u in users]


@router.get("/members")
async def list_org_members(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Return all active org members — accessible to any authenticated user."""
    members = db.query(User).filter(
        User.org_id == user.org_id,
        User.status == "active",
    ).order_by(User.name).all()
    return [
        {
            "id":           u.id,
            "name":         u.name,
            "email":        u.email,
            "role":         u.role,
            "pod":          u.pod,
            "emp_no":       u.emp_no,
            "reporting_to": u.reporting_to,
            "title":        u.title,
        }
        for u in members
    ]


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: str,
    db:      Session = Depends(get_db),
    actor:   User    = Depends(get_current_user),
):
    # Users can view their own profile; admins can view anyone in the org
    if user_id != actor.id and actor.role != "admin":
        raise HTTPException(403, "Not authorised")

    target = db.query(User).filter(User.id == user_id, User.org_id == actor.org_id).first()
    if not target:
        raise HTTPException(404, "User not found")
    return UserOut.model_validate(target)


@router.patch("/{user_id}/status", response_model=UserOut)
async def toggle_user_status(
    user_id: str,
    db:      Session = Depends(get_db),
    admin:   User    = Depends(get_admin),
):
    target = db.query(User).filter(User.id == user_id, User.org_id == admin.org_id).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == admin.id:
        raise HTTPException(400, "Cannot deactivate yourself")

    target.status = "inactive" if target.status == "active" else "active"
    db.commit()
    db.refresh(target)
    return UserOut.model_validate(target)
