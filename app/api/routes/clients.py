"""
app/api/routes/clients.py — Client budget and burn-rate tracking.

Endpoints:
  POST /api/clients/budget             Set monthly hour budget per client (admin/manager)
  GET  /api/clients/burn-rate          Current month burn % per client with NOVA summary
  GET  /api/clients/burn-rate/alerts   History of fired burn-rate alerts
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_manager_up

router = APIRouter(prefix="/api/clients", tags=["clients"])


# ── Schemas ────────────────────────────────────────────────────────────────

class BudgetCreate(BaseModel):
    client:       str
    month:        int
    year:         int
    budget_hours: float


# ── Routes ─────────────────────────────────────────────────────────────────

@router.post("/budget", status_code=201)
async def set_budget(
    body: BudgetCreate,
    db:   Session = Depends(get_db),
    user = Depends(get_manager_up),
):
    """Upsert a monthly hour budget for a client."""
    from app.models.client import ClientBudget
    from app.models.base import gen_uuid

    if not (1 <= body.month <= 12):
        raise HTTPException(400, "month must be 1–12")
    if body.budget_hours <= 0:
        raise HTTPException(400, "budget_hours must be > 0")

    existing = db.query(ClientBudget).filter(
        ClientBudget.org_id == user.org_id,
        ClientBudget.client == body.client,
        ClientBudget.month  == body.month,
        ClientBudget.year   == body.year,
    ).first()

    if existing:
        existing.budget_hours = body.budget_hours
        db.commit()
        db.refresh(existing)
        return existing
    else:
        budget = ClientBudget(
            id=gen_uuid(),
            org_id=user.org_id,
            client=body.client,
            month=body.month,
            year=body.year,
            budget_hours=body.budget_hours,
        )
        db.add(budget)
        db.commit()
        db.refresh(budget)
        return budget


@router.get("/burn-rate")
async def get_burn_rate(
    month: Optional[int] = None,
    year:  Optional[int] = None,
    db:    Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Return current burn % per client for the given month (defaults to current month)."""
    from app.models.client import ClientBudget
    from app.models.ticket import Worklog, JiraTicket
    from app.models.manual_entry import ManualEntry

    today = date.today()
    m = month or today.month
    y = year  or today.year

    budgets = db.query(ClientBudget).filter(
        ClientBudget.org_id == user.org_id,
        ClientBudget.month  == m,
        ClientBudget.year   == y,
    ).all()

    if not budgets:
        return []

    results = []
    for b in budgets:
        # Sum worklogs for this client this month
        wl_hours = db.query(func.sum(Worklog.hours)).join(
            JiraTicket, Worklog.ticket_id == JiraTicket.id
        ).filter(
            JiraTicket.org_id    == user.org_id,
            JiraTicket.client    == b.client,
            JiraTicket.is_deleted == False,
            func.extract("month", Worklog.log_date) == m,
            func.extract("year",  Worklog.log_date) == y,
        ).scalar() or 0

        # Sum manual entries for this client this month
        me_hours = db.query(func.sum(ManualEntry.hours)).filter(
            ManualEntry.org_id == user.org_id,
            ManualEntry.client == b.client,
            func.extract("month", ManualEntry.entry_date) == m,
            func.extract("year",  ManualEntry.entry_date) == y,
        ).scalar() or 0

        total_used = float(wl_hours) + float(me_hours)
        burn_pct   = round(total_used / float(b.budget_hours) * 100, 1) if b.budget_hours else 0

        results.append({
            "client":       b.client,
            "month":        m,
            "year":         y,
            "budget_hours": float(b.budget_hours),
            "hours_used":   round(total_used, 2),
            "burn_pct":     burn_pct,
            "status":       (
                "over_budget"  if burn_pct >= 100 else
                "critical"     if burn_pct >= 85  else
                "warning"      if burn_pct >= 70  else
                "on_track"
            ),
        })

    return results


@router.get("/burn-rate/alerts")
async def get_burn_rate_alerts(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Return history of fired burn-rate alerts for the org."""
    from app.models.client import BurnRateAlert

    alerts = db.query(BurnRateAlert).filter(
        BurnRateAlert.org_id == user.org_id
    ).order_by(BurnRateAlert.notified_at.desc()).limit(100).all()

    return [
        {
            "id":            a.id,
            "client":        a.client,
            "threshold_pct": a.threshold_pct,
            "hours_used":    float(a.hours_used)   if a.hours_used   else None,
            "hours_budget":  float(a.hours_budget) if a.hours_budget else None,
            "burn_pct":      round(float(a.hours_used) / float(a.hours_budget) * 100, 1)
                             if a.hours_used and a.hours_budget else None,
            "nova_summary":  a.nova_summary,
            "notified_at":   a.notified_at.isoformat() if a.notified_at else None,
        }
        for a in alerts
    ]
