"""
app/api/routes/custom_fields.py — Custom field definitions CRUD.

Endpoints:
  GET    /api/spaces/{pod}/custom-fields
  POST   /api/spaces/{pod}/custom-fields
  PUT    /api/spaces/{pod}/custom-fields/{id}
  DELETE /api/spaces/{pod}/custom-fields/{id}
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.custom_field import CustomFieldDefinition
from app.models.user import User

router = APIRouter(prefix="/api/spaces", tags=["custom-fields"])


class CustomFieldCreate(BaseModel):
    name: str
    field_type: str  # text | number | select | date | checkbox
    options: Optional[List[str]] = None
    is_required: bool = False
    display_order: int = 0


class CustomFieldUpdate(BaseModel):
    name: Optional[str] = None
    field_type: Optional[str] = None
    options: Optional[List[str]] = None
    is_required: Optional[bool] = None
    display_order: Optional[int] = None


class CustomFieldOut(BaseModel):
    id: str
    org_id: str
    pod: str
    name: str
    field_type: str
    options: Optional[List[str]] = None
    is_required: bool
    display_order: int
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/{pod}/custom-fields", response_model=List[CustomFieldOut])
async def list_custom_fields(
    pod: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    fields = db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.org_id == user.org_id,
        CustomFieldDefinition.pod == pod,
    ).order_by(CustomFieldDefinition.display_order.asc()).all()
    return [_to_out(f) for f in fields]


@router.post("/{pod}/custom-fields", response_model=CustomFieldOut, status_code=201)
async def create_custom_field(
    pod: str,
    body: CustomFieldCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models.base import gen_uuid
    field = CustomFieldDefinition(
        id=gen_uuid(),
        org_id=user.org_id,
        pod=pod,
        name=body.name,
        field_type=body.field_type,
        options=body.options,
        is_required=body.is_required,
        display_order=body.display_order,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    return _to_out(field)


@router.put("/{pod}/custom-fields/{field_id}", response_model=CustomFieldOut)
async def update_custom_field(
    pod: str,
    field_id: str,
    body: CustomFieldUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    field = db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.id == field_id,
        CustomFieldDefinition.org_id == user.org_id,
        CustomFieldDefinition.pod == pod,
    ).first()
    if not field:
        raise HTTPException(404, "Custom field not found")

    for key, val in body.model_dump(exclude_none=True).items():
        setattr(field, key, val)

    db.commit()
    db.refresh(field)
    return _to_out(field)


@router.delete("/{pod}/custom-fields/{field_id}", status_code=204)
async def delete_custom_field(
    pod: str,
    field_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    field = db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.id == field_id,
        CustomFieldDefinition.org_id == user.org_id,
        CustomFieldDefinition.pod == pod,
    ).first()
    if not field:
        raise HTTPException(404, "Custom field not found")
    db.delete(field)
    db.commit()


def _to_out(f: CustomFieldDefinition) -> CustomFieldOut:
    return CustomFieldOut(
        id=f.id,
        org_id=f.org_id,
        pod=f.pod,
        name=f.name,
        field_type=f.field_type,
        options=f.options,
        is_required=f.is_required or False,
        display_order=f.display_order or 0,
        created_at=f.created_at.isoformat() if f.created_at else None,
    )
