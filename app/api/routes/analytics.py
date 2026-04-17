"""
app/api/routes/analytics.py — Workload and team analytics.

Endpoints:
  GET /api/analytics/workload    Hours per engineer per POD (current month)
  GET /api/analytics/pod-summary POD-level ticket + hours summary
  GET /api/analytics/velocity    Sprint velocity trend for org
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/workload")
async def workload(
    month: Optional[int] = Query(None),
    year:  Optional[int] = Query(None),
    pod:   Optional[str] = Query(None),
    db:    Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Hours logged per engineer per POD for the given month."""
    from app.models.ticket import Worklog, JiraTicket

    today = date.today()
    m = month or today.month
    y = year  or today.year

    q = db.query(
        JiraTicket.assignee,
        JiraTicket.pod,
        func.sum(Worklog.hours).label("total_hours"),
    ).join(
        Worklog, Worklog.ticket_id == JiraTicket.id
    ).filter(
        JiraTicket.org_id    == user.org_id,
        JiraTicket.is_deleted == False,
        func.extract("month", Worklog.log_date) == m,
        func.extract("year",  Worklog.log_date) == y,
    ).group_by(JiraTicket.assignee, JiraTicket.pod)

    if pod:
        q = q.filter(JiraTicket.pod == pod)

    rows = q.order_by(JiraTicket.pod, JiraTicket.assignee).all()

    return {
        "month": m,
        "year":  y,
        "data": [
            {
                "engineer":    r.assignee or None,
                "pod":         r.pod or None,
                "total_hours": round(float(r.total_hours), 2),
            }
            for r in rows
        ],
    }


@router.get("/pod-summary")
async def pod_summary(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """POD-level breakdown: ticket counts by status and total hours."""
    from app.models.ticket import JiraTicket, Worklog
    from app.models.sprint import Sprint

    pod_tickets = db.query(
        JiraTicket.pod,
        JiraTicket.status,
        func.count(JiraTicket.id).label("count"),
    ).filter(
        JiraTicket.org_id    == user.org_id,
        JiraTicket.is_deleted == False,
    ).group_by(JiraTicket.pod, JiraTicket.status).all()

    # Aggregate by pod (skip tickets with no pod name)
    pods: dict = {}
    for row in pod_tickets:
        p = (row.pod or "").strip()
        if not p:
            continue
        if p not in pods:
            pods[p] = {"pod": p, "statuses": {}, "total_hours": 0}
        pods[p]["statuses"][row.status or ""] = row.count

    # Add hours
    pod_hours = db.query(
        JiraTicket.pod,
        func.sum(Worklog.hours).label("total_hours"),
    ).join(
        Worklog, Worklog.ticket_id == JiraTicket.id
    ).filter(
        JiraTicket.org_id    == user.org_id,
        JiraTicket.is_deleted == False,
    ).group_by(JiraTicket.pod).all()

    for row in pod_hours:
        p = row.pod or ""
        if p in pods:
            pods[p]["total_hours"] = round(float(row.total_hours), 2)

    # Include pods that exist as sprints but have no tickets yet (skip empty names)
    sprint_pods = db.query(Sprint.pod).filter(
        Sprint.org_id == user.org_id,
    ).distinct().all()
    for (spod,) in sprint_pods:
        p = (spod or "").strip()
        if p and p not in pods:
            pods[p] = {"pod": p, "statuses": {}, "total_hours": 0}

    return list(pods.values())


@router.get("/velocity")
async def velocity_trend(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Sprint velocity trend — last 10 completed sprints."""
    from app.models.sprint import Sprint

    sprints = db.query(Sprint).filter(
        Sprint.org_id  == user.org_id,
        Sprint.status  == "completed",
        Sprint.velocity != None,
    ).order_by(Sprint.end_date.desc()).limit(10).all()

    return [
        {
            "sprint_name":      s.name,
            "points_completed": s.velocity,
            "end_date":         s.end_date.isoformat() if s.end_date else None,
        }
        for s in reversed(sprints)
    ]
