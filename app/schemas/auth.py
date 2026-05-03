from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class SetPasswordRequest(BaseModel):
    password: str


class UserOut(BaseModel):
    id:           str
    name:         str
    email:        str
    role:         str
    pod:          Optional[str] = None
    pods:         Optional[str] = None
    emp_no:       Optional[str] = None
    title:        Optional[str] = None
    reporting_to: Optional[str] = None
    status:       str
    org_id:       str
    last_login:   Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    pod:  Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         UserOut
