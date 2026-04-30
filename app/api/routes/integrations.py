"""
app/api/routes/integrations.py — Slack / Teams / generic webhook integrations.

Endpoints:
  GET    /api/integrations           List org integrations
  POST   /api/integrations           Create integration
  PUT    /api/integrations/:id       Update integration
  DELETE /api/integrations/:id       Delete integration
  POST   /api/integrations/:id/test  Send a test webhook
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.integration import Integration
from app.models.base import gen_uuid
from app.models.user import User

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

VALID_TYPES = {"slack", "teams", "generic_webhook"}
VALID_EVENTS = {
    "ticket_created",
    "status_changed",
    "sprint_started",
    "sprint_completed",
    "mention",
    "comment_added",
}


class IntegrationCreate(BaseModel):
    name: str
    type: str
    webhook_url: str
    events: List[str] = []
    is_active: bool = True


class IntegrationUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    webhook_url: Optional[str] = None
    events: Optional[List[str]] = None
    is_active: Optional[bool] = None


class IntegrationOut(BaseModel):
    id: str
    name: str
    type: str
    webhook_url: str
    events: List[str]
    is_active: bool
    created_at: Optional[str]

    model_config = {"from_attributes": True}


def _to_out(i: Integration) -> IntegrationOut:
    return IntegrationOut(
        id=i.id,
        name=i.name,
        type=i.type,
        webhook_url=i.webhook_url,
        events=i.events or [],
        is_active=i.is_active,
        created_at=i.created_at.isoformat() if i.created_at else None,
    )


@router.get("", response_model=List[IntegrationOut])
async def list_integrations(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    rows = db.query(Integration).filter(
        Integration.org_id == user.org_id,
    ).order_by(Integration.created_at.desc()).all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=IntegrationOut, status_code=201)
async def create_integration(
    payload: IntegrationCreate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    if payload.type not in VALID_TYPES:
        raise HTTPException(400, f"type must be one of {sorted(VALID_TYPES)}")
    bad_events = set(payload.events) - VALID_EVENTS
    if bad_events:
        raise HTTPException(400, f"Unknown events: {bad_events}")

    row = Integration(
        id=gen_uuid(),
        org_id=user.org_id,
        name=payload.name,
        type=payload.type,
        webhook_url=payload.webhook_url,
        events=payload.events,
        is_active=payload.is_active,
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.put("/{integration_id}", response_model=IntegrationOut)
async def update_integration(
    integration_id: str,
    payload: IntegrationUpdate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    row = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.org_id == user.org_id,
    ).first()
    if not row:
        raise HTTPException(404, "Integration not found")

    if payload.type and payload.type not in VALID_TYPES:
        raise HTTPException(400, f"type must be one of {sorted(VALID_TYPES)}")
    if payload.events is not None:
        bad_events = set(payload.events) - VALID_EVENTS
        if bad_events:
            raise HTTPException(400, f"Unknown events: {bad_events}")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    row = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.org_id == user.org_id,
    ).first()
    if not row:
        raise HTTPException(404, "Integration not found")
    db.delete(row)
    db.commit()


@router.post("/{integration_id}/test")
async def test_integration(
    integration_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    row = db.query(Integration).filter(
        Integration.id == integration_id,
        Integration.org_id == user.org_id,
    ).first()
    if not row:
        raise HTTPException(404, "Integration not found")

    from app.services.webhook_service import test_webhook
    success = await test_webhook(row.webhook_url, row.type)
    if not success:
        raise HTTPException(502, "Test webhook failed — check the URL and try again")
    return {"ok": True, "message": "Test message sent successfully"}
