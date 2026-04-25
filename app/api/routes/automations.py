"""
app/api/routes/automations.py — Automation rules CRUD.

Endpoints:
  GET    /api/spaces/{pod}/automations
  POST   /api/spaces/{pod}/automations
  PUT    /api/spaces/{pod}/automations/{id}
  DELETE /api/spaces/{pod}/automations/{id}
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.automation import AutomationRule

router = APIRouter(prefix="/api/spaces", tags=["automations"])


class AutomationCreatePayload(BaseModel):
    name: str
    is_active: bool = True
    trigger_type: str
    trigger_config: dict = Field(default_factory=dict)
    condition_type: Optional[str] = None
    condition_config: Optional[dict] = None
    action_type: str
    action_config: dict = Field(default_factory=dict)


class AutomationUpdatePayload(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    trigger_type: Optional[str] = None
    trigger_config: Optional[dict] = None
    condition_type: Optional[str] = None
    condition_config: Optional[dict] = None
    action_type: Optional[str] = None
    action_config: Optional[dict] = None


class AutomationOut(BaseModel):
    id: str
    name: str
    is_active: bool
    trigger_type: str
    trigger_config: dict
    condition_type: Optional[str]
    condition_config: Optional[dict]
    action_type: str
    action_config: dict
    run_count: int
    created_at: Optional[str]

    model_config = {"from_attributes": True}


@router.get("/{pod}/automations", response_model=List[AutomationOut])
async def list_automations(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    rules = db.query(AutomationRule).filter(
        AutomationRule.org_id == user.org_id,
        AutomationRule.pod == pod,
    ).order_by(AutomationRule.created_at.desc()).all()
    return [_to_out(r) for r in rules]


@router.post("/{pod}/automations", response_model=AutomationOut, status_code=201)
async def create_automation(
    pod: str,
    payload: AutomationCreatePayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.base import gen_uuid
    rule = AutomationRule(
        id=gen_uuid(),
        org_id=user.org_id,
        pod=pod,
        name=payload.name,
        is_active=payload.is_active,
        trigger_type=payload.trigger_type,
        trigger_config=payload.trigger_config,
        condition_type=payload.condition_type,
        condition_config=payload.condition_config,
        action_type=payload.action_type,
        action_config=payload.action_config,
        created_by=user.id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.put("/{pod}/automations/{rule_id}", response_model=AutomationOut)
async def update_automation(
    pod: str,
    rule_id: str,
    payload: AutomationUpdatePayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    rule = db.query(AutomationRule).filter(
        AutomationRule.id == rule_id,
        AutomationRule.org_id == user.org_id,
        AutomationRule.pod == pod,
    ).first()
    if not rule:
        raise HTTPException(404, "Automation rule not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(rule, field, value)

    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.delete("/{pod}/automations/{rule_id}", status_code=204)
async def delete_automation(
    pod: str,
    rule_id: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    rule = db.query(AutomationRule).filter(
        AutomationRule.id == rule_id,
        AutomationRule.org_id == user.org_id,
        AutomationRule.pod == pod,
    ).first()
    if not rule:
        raise HTTPException(404, "Automation rule not found")
    db.delete(rule)
    db.commit()


def _to_out(rule: AutomationRule) -> AutomationOut:
    return AutomationOut(
        id=rule.id,
        name=rule.name,
        is_active=rule.is_active,
        trigger_type=rule.trigger_type,
        trigger_config=rule.trigger_config or {},
        condition_type=rule.condition_type,
        condition_config=rule.condition_config,
        action_type=rule.action_type,
        action_config=rule.action_config or {},
        run_count=rule.run_count or 0,
        created_at=rule.created_at.isoformat() if rule.created_at else None,
    )
