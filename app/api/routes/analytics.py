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


@router.get("/bug-cost")
async def bug_cost(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Real Cost of Bug: total engineering hours and estimated spend on bug tickets."""
    from app.models.ticket import JiraTicket

    org_id           = user.org_id
    AVG_HOURLY_RATE  = 75  # USD, placeholder rate

    bugs = db.query(JiraTicket).filter(
        JiraTicket.org_id     == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.issue_type == "Bug",
    ).all()

    DONE               = {"Done", "Closed", "Resolved"}
    total_bugs         = len(bugs)
    total_bug_hours    = sum(b.hours_spent or 0 for b in bugs)
    open_bugs          = [b for b in bugs if (b.status or "") not in DONE]
    high_priority_bugs = [b for b in bugs if (b.priority or "") in ("High", "Highest")]

    pod_data: dict = {}
    for bug in bugs:
        pod = (bug.pod or "").strip() or "Unknown"
        if pod not in pod_data:
            pod_data[pod] = {"pod": pod, "count": 0, "hours": 0.0, "open": 0}
        pod_data[pod]["count"] += 1
        pod_data[pod]["hours"]  = round(pod_data[pod]["hours"] + (bug.hours_spent or 0), 2)
        if (bug.status or "") not in DONE:
            pod_data[pod]["open"] += 1

    by_pod = sorted(
        [
            {
                "pod":      p["pod"],
                "count":    p["count"],
                "hours":    round(p["hours"], 1),
                "open":     p["open"],
                "cost_usd": round(p["hours"] * AVG_HOURLY_RATE, 2),
            }
            for p in pod_data.values()
        ],
        key=lambda x: x["hours"],
        reverse=True,
    )

    return {
        "total_bugs":         total_bugs,
        "open_bugs":          len(open_bugs),
        "high_priority_bugs": len(high_priority_bugs),
        "total_hours":        round(total_bug_hours, 1),
        "total_cost_usd":     round(total_bug_hours * AVG_HOURLY_RATE, 2),
        "avg_hours_per_bug":  round(total_bug_hours / max(1, total_bugs), 1),
        "avg_hourly_rate":    AVG_HOURLY_RATE,
        "by_pod":             by_pod,
    }


@router.get("/recurring-problems")
async def recurring_problems(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Detect recurring bug patterns from repeated keywords in ticket summaries."""
    from app.models.ticket import JiraTicket
    import re

    org_id = user.org_id

    bugs = db.query(JiraTicket).filter(
        JiraTicket.org_id     == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.issue_type == "Bug",
    ).all()

    STOP = {
        "the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
        "and", "or", "with", "bug", "issue", "error", "fix", "not",
        "no", "does", "when", "that", "this", "from", "into", "after",
        "have", "has", "been", "were", "will", "should", "could", "would",
    }

    keyword_tickets: dict = {}
    for bug in bugs:
        words = re.findall(r"\b[a-z]{4,}\b", (bug.summary or "").lower())
        for word in words:
            if word not in STOP:
                if word not in keyword_tickets:
                    keyword_tickets[word] = []
                keyword_tickets[word].append(bug.jira_key)

    patterns = [
        {
            "pattern":     k,
            "occurrences": len(v),
            "ticket_keys": v[:5],
            "severity":    "high"   if len(v) >= 6
                           else "medium" if len(v) >= 4
                           else "low",
        }
        for k, v in keyword_tickets.items()
        if len(v) >= 3
    ]
    patterns.sort(key=lambda x: x["occurrences"], reverse=True)

    return {
        "patterns":            patterns[:10],
        "total_bugs_analyzed": len(bugs),
    }


@router.get("/client-health")
async def client_health(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Per-client delivery health score: delivery rate, bug rate, blockers, overdue."""
    from app.models.ticket import JiraTicket
    from datetime import date
    from collections import defaultdict

    org_id = user.org_id
    today  = date.today()
    DONE   = {"Done", "Closed", "Resolved"}

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id     == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.client     != None,
        JiraTicket.client     != "",
    ).all()

    buckets: dict = defaultdict(lambda: {
        "total": 0, "done": 0, "blocked": 0, "bugs": 0, "overdue": 0, "hours": 0.0,
    })

    for t in tickets:
        c = (t.client or "").strip()
        if not c:
            continue
        buckets[c]["total"]  += 1
        buckets[c]["hours"]  += t.hours_spent or 0
        if (t.status or "") in DONE:
            buckets[c]["done"] += 1
        if "block" in (t.status or "").lower():
            buckets[c]["blocked"] += 1
        if (t.issue_type or "") == "Bug":
            buckets[c]["bugs"] += 1
        if t.due_date and t.due_date < today and (t.status or "") not in DONE:
            buckets[c]["overdue"] += 1

    result = []
    for client_name, data in buckets.items():
        total         = max(1, data["total"])
        delivery_rate = round(data["done"]    / total * 100)
        bug_rate      = round(data["bugs"]    / total * 100)
        block_rate    = round(data["blocked"] / total * 100)
        overdue_rate  = round(data["overdue"] / total * 100)

        health_score = max(0, min(100,
            delivery_rate
            - bug_rate     * 0.5
            - block_rate   * 1.5
            - overdue_rate * 2.0
        ))

        result.append({
            "client":          client_name,
            "health_score":    round(health_score),
            "status":          ("Healthy"  if health_score >= 70
                                else "At Risk"  if health_score >= 40
                                else "Critical"),
            "total_tickets":   data["total"],
            "done_tickets":    data["done"],
            "delivery_rate":   delivery_rate,
            "bug_rate":        bug_rate,
            "blocked_tickets": data["blocked"],
            "overdue_tickets": data["overdue"],
            "total_hours":     round(data["hours"], 1),
        })

    return sorted(result, key=lambda x: x["health_score"])
