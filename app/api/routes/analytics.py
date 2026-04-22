"""
app/api/routes/analytics.py — Workload and team analytics.

Endpoints:
  GET /api/analytics/workload    Hours per engineer per POD (current month)
  GET /api/analytics/pod-summary POD-level ticket + hours summary with health scores
  GET /api/analytics/velocity    Sprint velocity trend for org
  GET /api/analytics/capacity    Engineer capacity and workload % per pod
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
    """
    POD-level breakdown: ticket counts by status, total hours, and unified health scores.
    Health scores come from health_service so they match /spaces/{pod}/health exactly.
    """
    from app.models.ticket import JiraTicket, Worklog
    from app.models.sprint import Sprint
    from app.services.health_service import compute_health

    org_id = user.org_id

    pod_tickets = db.query(
        JiraTicket.pod,
        JiraTicket.status,
        func.count(JiraTicket.id).label("count"),
    ).filter(
        JiraTicket.org_id    == org_id,
        JiraTicket.is_deleted == False,
    ).group_by(JiraTicket.pod, JiraTicket.status).all()

    # Aggregate by pod
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
        JiraTicket.org_id    == org_id,
        JiraTicket.is_deleted == False,
    ).group_by(JiraTicket.pod).all()

    for row in pod_hours:
        p = row.pod or ""
        if p in pods:
            pods[p]["total_hours"] = round(float(row.total_hours), 2)

    # Include sprint-only pods
    sprint_pods = db.query(Sprint.pod).filter(
        Sprint.org_id == org_id,
    ).distinct().all()
    for (spod,) in sprint_pods:
        p = (spod or "").strip()
        if p and p not in pods:
            pods[p] = {"pod": p, "statuses": {}, "total_hours": 0}

    # Attach unified health scores (same algorithm as /spaces/{pod}/health)
    for p, data in pods.items():
        tickets = db.query(JiraTicket).filter(
            JiraTicket.org_id == org_id,
            JiraTicket.pod == p,
            JiraTicket.is_deleted == False,
        ).all()
        active_sprint = db.query(Sprint).filter(
            Sprint.org_id == org_id,
            Sprint.pod == p,
            Sprint.status == "active",
        ).first()
        health = compute_health(tickets, active_sprint)
        data["health_score"]        = health["health_score"]
        data["delivery_confidence"] = health["delivery_confidence"]
        data["sprint_prediction"]   = health["sprint_prediction"]
        data["has_active_sprint"]   = active_sprint is not None
        data["risk_flags"]          = health["risk_flags"]

    return list(pods.values())


@router.get("/capacity")
async def capacity(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Engineer capacity per pod: story points allocated vs estimated capacity.
    Powers EOSIntelligencePanel → Capacity tab.

    capacity_pct: 0-100+ where 100 = fully loaded, >85 = overloaded.
    """
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint

    org_id = user.org_id

    # Active sprint story points per assignee per pod
    active_sprints = db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.status == "active",
    ).all()

    if not active_sprints:
        # Fall back to all open tickets if no active sprints
        rows = db.query(
            JiraTicket.assignee,
            JiraTicket.pod,
            func.sum(JiraTicket.story_points).label("pts"),
            func.count(JiraTicket.id).label("ticket_count"),
        ).filter(
            JiraTicket.org_id == org_id,
            JiraTicket.is_deleted == False,
            JiraTicket.assignee != None,
            JiraTicket.pod != None,
            JiraTicket.status.notin_(["Done", "Closed", "Resolved"]),
        ).group_by(JiraTicket.assignee, JiraTicket.pod).all()
    else:
        sprint_ids = [s.id for s in active_sprints]
        rows = db.query(
            JiraTicket.assignee,
            JiraTicket.pod,
            func.sum(JiraTicket.story_points).label("pts"),
            func.count(JiraTicket.id).label("ticket_count"),
        ).filter(
            JiraTicket.org_id == org_id,
            JiraTicket.sprint_id.in_(sprint_ids),
            JiraTicket.is_deleted == False,
            JiraTicket.assignee != None,
            JiraTicket.pod != None,
        ).group_by(JiraTicket.assignee, JiraTicket.pod).all()

    # Standard sprint capacity = 40 pts per engineer per 2-week sprint
    CAPACITY_BASELINE = 40

    result = []
    for row in rows:
        pts = int(row.pts or 0)
        capacity_pct = round((pts / CAPACITY_BASELINE) * 100) if pts > 0 else 0
        result.append({
            "engineer":     row.assignee,
            "pod":          row.pod,
            "allocated_pts": pts,
            "ticket_count": row.ticket_count,
            "capacity_pct": capacity_pct,
            "overloaded":   capacity_pct > 85,
        })

    result.sort(key=lambda r: r["capacity_pct"], reverse=True)
    return result


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
