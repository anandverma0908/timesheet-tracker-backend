"""
app/api/routes/summary.py — Org-wide summary + per-engineer stats.

Endpoints:
  GET /api/summary         Aggregate hours/tickets by user, client, pod, issue_type
  GET /api/engineer-stats  Per-engineer stats (hours, tickets, active days)
"""

from datetime import date
from typing import Optional
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api", tags=["summary"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_list(val: Optional[str]) -> list[str]:
    if not val:
        return []
    return [v.strip() for v in val.split(",") if v.strip()]


# ── /api/summary ───────────────────────────────────────────────────────────────

@router.get("/summary")
async def summary(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    user:      Optional[str] = Query(None),
    pod:       Optional[str] = Query(None),
    client:    Optional[str] = Query(None),
    project:   Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Aggregate hours (worklogs + manual entries) and ticket counts
    broken down by user, client, POD, and issue type.
    """
    from app.models.ticket import JiraTicket, Worklog
    from app.models.manual_entry import ManualEntry
    from app.models.user import User

    pod_list    = _parse_list(pod)
    client_list = _parse_list(client)

    df = date.fromisoformat(date_from) if date_from else None
    dt = date.fromisoformat(date_to)   if date_to   else None

    # ── 1. Worklog-based hours ──────────────────────────────────────────────────
    wl_q = (
        db.query(Worklog, JiraTicket)
        .join(JiraTicket, Worklog.ticket_id == JiraTicket.id)
        .filter(
            JiraTicket.org_id    == current_user.org_id,
            JiraTicket.is_deleted == False,
        )
    )
    if df:  wl_q = wl_q.filter(Worklog.log_date >= df)
    if dt:  wl_q = wl_q.filter(Worklog.log_date <= dt)
    if user:         wl_q = wl_q.filter(Worklog.author == user)
    if pod_list:     wl_q = wl_q.filter(JiraTicket.pod.in_(pod_list))
    if client_list:  wl_q = wl_q.filter(JiraTicket.client.in_(client_list))
    if project:      wl_q = wl_q.filter(JiraTicket.project_key == project)

    worklogs = wl_q.all()

    # ── 2. Manual-entry hours ───────────────────────────────────────────────────
    me_q = (
        db.query(ManualEntry, User)
        .join(User, ManualEntry.user_id == User.id)
        .filter(ManualEntry.org_id == current_user.org_id)
    )
    if df:  me_q = me_q.filter(ManualEntry.entry_date >= df)
    if dt:  me_q = me_q.filter(ManualEntry.entry_date <= dt)
    if user:         me_q = me_q.filter(User.name == user)
    if pod_list:     me_q = me_q.filter(ManualEntry.pod.in_(pod_list))
    if client_list:  me_q = me_q.filter(ManualEntry.client.in_(client_list))

    manual_entries = me_q.all()

    # ── 3. Ticket counts (not filtered by date — open tickets) ─────────────────
    tk_q = db.query(JiraTicket).filter(
        JiraTicket.org_id    == current_user.org_id,
        JiraTicket.is_deleted == False,
    )
    if user:         tk_q = tk_q.filter(JiraTicket.assignee == user)
    if pod_list:     tk_q = tk_q.filter(JiraTicket.pod.in_(pod_list))
    if client_list:  tk_q = tk_q.filter(JiraTicket.client.in_(client_list))
    if project:      tk_q = tk_q.filter(JiraTicket.project_key == project)

    tickets = tk_q.all()

    # ── 4. Aggregate ───────────────────────────────────────────────────────────
    user_hours:   dict[str, float]      = defaultdict(float)
    user_clients: dict[str, set]        = defaultdict(set)
    client_hours: dict[str, float]      = defaultdict(float)
    client_users: dict[str, set]        = defaultdict(set)
    pod_hours:    dict[str, float]      = defaultdict(float)
    pod_clients:  dict[str, set]        = defaultdict(set)
    itype_hours:  dict[str, float]      = defaultdict(float)

    for wl, tk in worklogs:
        author = wl.author or tk.assignee or "Unknown"
        c  = tk.client or "—"
        p  = tk.pod    or "—"
        it = tk.issue_type or "Other"
        h  = float(wl.hours or 0)

        user_hours[author]  += h
        user_clients[author].add(c)
        client_hours[c]     += h
        client_users[c].add(author)
        pod_hours[p]        += h
        pod_clients[p].add(c)
        itype_hours[it]     += h

    for me, u in manual_entries:
        author = u.name or "Unknown"
        c  = me.client or "—"
        p  = me.pod    or "—"
        h  = float(me.hours or 0)

        user_hours[author]  += h
        user_clients[author].add(c)
        client_hours[c]     += h
        client_users[c].add(author)
        pod_hours[p]        += h
        pod_clients[p].add(c)

    # Ticket counts per user/client/pod/issue_type
    user_tickets:   dict[str, int] = defaultdict(int)
    client_tickets: dict[str, int] = defaultdict(int)
    pod_tickets:    dict[str, int] = defaultdict(int)
    itype_tickets:  dict[str, int] = defaultdict(int)

    for tk in tickets:
        a  = tk.assignee   or "Unknown"
        c  = tk.client     or "—"
        p  = tk.pod        or "—"
        it = tk.issue_type or "Other"
        user_tickets[a]   += 1
        client_tickets[c] += 1
        pod_tickets[p]    += 1
        itype_tickets[it] += 1

    total_hours   = round(sum(user_hours.values()), 2)
    total_tickets = len(tickets)

    # issue_type percentage
    total_it_hours = sum(itype_hours.values()) or 1

    by_user = [
        {
            "user":    u,
            "hours":   round(h, 2),
            "tickets": user_tickets.get(u, 0),
            "clients": sorted(user_clients[u]),
        }
        for u, h in sorted(user_hours.items(), key=lambda x: -x[1])
    ]
    # Include users who have tickets but no hours
    tracked_users = {e["user"] for e in by_user}
    for u, cnt in user_tickets.items():
        if u not in tracked_users:
            by_user.append({"user": u, "hours": 0.0, "tickets": cnt, "clients": []})

    by_client = [
        {
            "client":  c,
            "hours":   round(h, 2),
            "tickets": client_tickets.get(c, 0),
            "users":   sorted(client_users[c]),
        }
        for c, h in sorted(client_hours.items(), key=lambda x: -x[1])
    ]

    by_pod = [
        {
            "pod":     p,
            "hours":   round(h, 2),
            "tickets": pod_tickets.get(p, 0),
            "clients": sorted(pod_clients[p]),
        }
        for p, h in sorted(pod_hours.items(), key=lambda x: -x[1])
    ]
    # Include pods with tickets but no hours
    tracked_pods = {e["pod"] for e in by_pod}
    for p, cnt in pod_tickets.items():
        if p not in tracked_pods:
            by_pod.append({"pod": p, "hours": 0.0, "tickets": cnt, "clients": []})

    by_issue_type = [
        {
            "issue_type": it,
            "hours":  round(h, 2),
            "tickets": itype_tickets.get(it, 0),
            "pct":    round(h / total_it_hours * 100, 1),
        }
        for it, h in sorted(itype_hours.items(), key=lambda x: -x[1])
    ]

    return {
        "by_user":       by_user,
        "by_client":     by_client,
        "by_pod":        by_pod,
        "by_issue_type": by_issue_type,
        "total_tickets": total_tickets,
        "total_hours":   total_hours,
    }


# ── /api/engineer-stats ────────────────────────────────────────────────────────

@router.get("/engineer-stats")
async def engineer_stats(
    user:      str            = Query(...),
    date_from: Optional[str]  = Query(None),
    date_to:   Optional[str]  = Query(None),
    pod:       Optional[str]  = Query(None),
    client:    Optional[str]  = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """Per-engineer stats: hours, manual_hours, tickets, manual_entries, active_days, clients."""
    from app.models.ticket import JiraTicket, Worklog
    from app.models.manual_entry import ManualEntry
    from app.models.user import User

    pod_list    = _parse_list(pod)
    client_list = _parse_list(client)
    df = date.fromisoformat(date_from) if date_from else None
    dt = date.fromisoformat(date_to)   if date_to   else None

    # Worklogs
    wl_q = (
        db.query(Worklog)
        .join(JiraTicket, Worklog.ticket_id == JiraTicket.id)
        .filter(
            JiraTicket.org_id    == current_user.org_id,
            JiraTicket.is_deleted == False,
            Worklog.author       == user,
        )
    )
    if df: wl_q = wl_q.filter(Worklog.log_date >= df)
    if dt: wl_q = wl_q.filter(Worklog.log_date <= dt)
    if pod_list:    wl_q = wl_q.filter(JiraTicket.pod.in_(pod_list))
    if client_list: wl_q = wl_q.filter(JiraTicket.client.in_(client_list))
    worklogs = wl_q.all()

    # Manual entries
    u_obj = db.query(User).filter(User.name == user, User.org_id == current_user.org_id).first()
    manual_entries = []
    if u_obj:
        me_q = db.query(ManualEntry).filter(
            ManualEntry.org_id   == current_user.org_id,
            ManualEntry.user_id  == u_obj.id,
        )
        if df: me_q = me_q.filter(ManualEntry.entry_date >= df)
        if dt: me_q = me_q.filter(ManualEntry.entry_date <= dt)
        if pod_list:    me_q = me_q.filter(ManualEntry.pod.in_(pod_list))
        if client_list: me_q = me_q.filter(ManualEntry.client.in_(client_list))
        manual_entries = me_q.all()

    # Ticket count
    tk_q = db.query(JiraTicket).filter(
        JiraTicket.org_id    == current_user.org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.assignee  == user,
    )
    if pod_list:    tk_q = tk_q.filter(JiraTicket.pod.in_(pod_list))
    if client_list: tk_q = tk_q.filter(JiraTicket.client.in_(client_list))
    ticket_count = tk_q.count()

    wl_hours    = sum(float(w.hours or 0) for w in worklogs)
    me_hours    = sum(float(m.hours or 0) for m in manual_entries)
    active_days = len({w.log_date for w in worklogs} | {m.entry_date for m in manual_entries})

    return {
        "user":           user,
        "hours":          round(wl_hours + me_hours, 2),
        "manual_hours":   round(me_hours, 2),
        "tickets":        ticket_count,
        "manual_entries": len(manual_entries),
        "active_days":    active_days,
        "clients":        1,  # placeholder
    }
