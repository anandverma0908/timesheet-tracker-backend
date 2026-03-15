"""
auth.py — Password login, JWT tokens.
"""

import os
import bcrypt
from datetime import datetime, timedelta

from jose import JWTError, jwt
from sqlalchemy.orm import Session
from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from database import get_db, User, Organisation

JWT_SECRET       = os.getenv("JWT_SECRET", "change-this-secret")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

security = HTTPBearer()


# ── Password helpers ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_jwt(user: User) -> str:
    payload = {
        "sub":    user.id,
        "email":  user.email,
        "role":   user.role,
        "org_id": user.org_id,
        "pod":    user.pod,
        "exp":    datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_jwt(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )


# ── FastAPI auth dependencies ─────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_jwt(credentials.credentials)
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user or user.status == "inactive":
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user

def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(roles)}"
            )
        return user
    return checker

def get_admin(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


# ── Invite email (print only — configure SMTP separately if needed) ───────────

def send_invite_email(to_email: str, to_name: str, invited_by: str, org_name: str) -> None:
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    print(f"[INVITE] {to_name} <{to_email}> invited by {invited_by} to {org_name}")
    print(f"[INVITE] Login at: {frontend_url}/login")