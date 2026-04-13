"""
app/api/routes/auth.py — Authentication: login, me, set-password.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import verify_password, create_access_token, hash_password
from app.models.user import User
from app.schemas.auth import LoginRequest, SetPasswordRequest, UserOut, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    if user.status == "inactive":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is inactive")

    token = create_access_token({
        "sub":    user.id,
        "email":  user.email,
        "role":   user.role,
        "org_id": user.org_id,
        "pod":    user.pod,
    })
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/set-password", response_model=dict)
async def set_password(
    body: SetPasswordRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    user.password_hash = hash_password(body.password)
    db.commit()
    return {"message": "Password updated successfully"}
