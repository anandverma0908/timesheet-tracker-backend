"""
app/api/routes/spaces.py — Project/Space detail aggregation for the Spaces feature.

Endpoints:
  GET /api/spaces                  List all spaces with health scores
  GET /api/spaces/{pod}/project    Full project payload (matches frontend Project type)
  GET /api/spaces/{pod}/health     Unified health score + radar + risk flags
  GET /api/spaces/anomalies        Rule-based anomaly detection across all pods
  GET /api/spaces/dependencies     Cross-space blocker dependency map
  GET /api/spaces/{pod}/backlog    Tickets in this pod not assigned to any sprint
  GET /api/spaces/{pod}/epics      Epics for this pod
  POST /api/spaces                 Create a new space
  DELETE /api/spaces/{pod}         Delete a space and all its data
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_manager_up

router = APIRouter(prefix="/api/spaces", tags=["spaces"])


class SpaceCreatePayload(BaseModel):
    key: str
    name: str
    description: str
    category: str
    color: str


# ── Helpers ────────────────────────────────────────────────────────────────

POD_COLORS = {
    "DPAI": "#4F7EFF",
    "SNOP": "#A78BFA",
    "EDM":  "#FBBF24",
    "PLAT": "#34D399",
    "SNOE": "#22D3EE",
    "PA":   "#F87171",
}

MEMBER_COLORS = [
    "linear-gradient(135deg,#4F7EFF,#818CF8)",
    "linear-gradient(135deg,#34D399,#10B981)",
    "linear-gradient(135deg,#FBBF24,#F59E0B)",
    "linear-gradient(135deg,#F87171,#FCA5A5)",
    "linear-gradient(135deg,#A78BFA,#C4B5FD)",
    "linear-gradient(135deg,#22D3EE,#67E8F9)",
    "linear-gradient(135deg,#64748B,#94A3B8)",
    "linear-gradient(135deg,#FB923C,#FDBA74)",
]


def _hash_color(name: str) -> str:
    h = 0
    for c in name:
        h = (h * 31 + ord(c)) & 0xffffffff
    return MEMBER_COLORS[abs(h) % len(MEMBER_COLORS)]


def _initials(name: Optional[str]) -> str:
    if not name:
        return ""
    parts = name.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper()


def _normalize_status(s: Optional[str]) -> str:
    if not s:
        return "To Do"
    l = s.lower()
    if l in ("done", "closed", "resolved"):
        return "Done"
    if l == "blocked":
        return "Blocked"
    if "review" in l or "qa" in l:
        return "In Review"
    if "progress" in l or "development" in l:
        return "In Progress"
    return "To Do"


def _normalize_priority(p: Optional[str]) -> str:
    if not p:
        return "Medium"
    l = p.lower()
    if l in ("critical", "blocker"):
        return "Critical"
    if l == "high":
        return "High"
    if l in ("low", "minor", "trivial"):
        return "Low"
    return "Medium"


def _normalize_type(t: Optional[str]) -> str:
    if not t:
        return "Task"
    l = t.lower()
    if "bug" in l or "defect" in l:
        return "Bug"
    if "story" in l or "feature" in l:
        return "Story"
    if "epic" in l:
        return "Epic"
    if "subtask" in l or "sub-task" in l:
        return "Subtask"
    return "Task"


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_spaces(
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    List all spaces (pods) for the org with summary stats and unified health scores.
    Used by SpacesPage to populate the grid/list/heatmap views.
    """
    from app.models.ticket import JiraTicket, Worklog
    from app.models.sprint import Sprint
    from app.services.health_service import compute_health

    org_id = user.org_id

    # All distinct pods from tickets + sprints
    ticket_pods = db.query(JiraTicket.pod).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.pod != None,
    ).distinct().all()

    sprint_pods = db.query(Sprint.pod).filter(
        Sprint.org_id == org_id,
        Sprint.pod != None,
    ).distinct().all()

    all_pods = sorted({p for (p,) in ticket_pods + sprint_pods if (p or "").strip()})

    result = []
    for pod in all_pods:
        tickets = db.query(JiraTicket).filter(
            JiraTicket.org_id == org_id,
            JiraTicket.pod == pod,
            JiraTicket.is_deleted == False,
        ).all()

        active_sprint = db.query(Sprint).filter(
            Sprint.org_id == org_id,
            Sprint.pod == pod,
            Sprint.status == "active",
        ).first()

        health = compute_health(tickets, active_sprint)

        # Ticket counts
        done_keys     = {"done", "closed", "resolved"}
        n_done        = sum(1 for t in tickets if (t.status or "").lower() in done_keys)
        n_blocked     = sum(1 for t in tickets if (t.status or "").lower() == "blocked")
        n_in_progress = sum(1 for t in tickets if "progress" in (t.status or "").lower())

        total_hours_row = db.query(func.sum(Worklog.hours)).join(
            JiraTicket, JiraTicket.id == Worklog.ticket_id
        ).filter(
            JiraTicket.org_id == org_id,
            JiraTicket.pod == pod,
            JiraTicket.is_deleted == False,
        ).scalar() or 0

        result.append({
            "pod":                  pod,
            "color":                POD_COLORS.get(pod, "#8B8FA8"),
            "total_tickets":        len(tickets),
            "completed_tickets":    n_done,
            "in_progress_tickets":  n_in_progress,
            "blocked_tickets":      n_blocked,
            "total_hours":          round(float(total_hours_row), 2),
            "has_active_sprint":    active_sprint is not None,
            "sprint_name":          active_sprint.name if active_sprint else None,
            **health,  # health_score, radar, delivery_confidence, sprint_prediction, trend, risk_flags
        })

    return result


@router.get("/anomalies")
async def get_anomalies(
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Rule-based anomaly detection across all pods.
    Powers EOSIntelligencePanel → Anomalies tab.
    No LLM needed — deterministic rules over health metrics.
    """
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint
    from app.services.health_service import compute_health, detect_anomalies

    org_id = user.org_id

    pods = db.query(JiraTicket.pod).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.pod != None,
    ).distinct().all()

    all_anomalies = []
    for (pod,) in pods:
        if not (pod or "").strip():
            continue
        tickets = db.query(JiraTicket).filter(
            JiraTicket.org_id == org_id,
            JiraTicket.pod == pod,
            JiraTicket.is_deleted == False,
        ).all()
        active_sprint = db.query(Sprint).filter(
            Sprint.org_id == org_id,
            Sprint.pod == pod,
            Sprint.status == "active",
        ).first()
        health = compute_health(tickets, active_sprint)
        all_anomalies.extend(detect_anomalies(pod, health))

    # Sort by severity (high first)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_anomalies.sort(key=lambda a: severity_order.get(a["severity"], 9))
    return all_anomalies


@router.get("/dependencies")
async def get_dependencies(
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Cross-space dependency map: blocked tickets that affect other pods.
    Powers EOSIntelligencePanel → Deps tab.

    Strategy: find Blocked tickets, then look for tickets in OTHER pods
    that reference the same client/epic/sprint context (same sprint = shared dependency).
    """
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint

    org_id = user.org_id

    blocked_tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.status.ilike("blocked"),
    ).all()

    deps = []
    seen = set()

    for bt in blocked_tickets:
        if not bt.pod:
            continue

        # Find pods sharing the same sprint (cross-pod sprint = dependency)
        if bt.sprint_id:
            sprint_mates = db.query(JiraTicket.pod).filter(
                JiraTicket.sprint_id == bt.sprint_id,
                JiraTicket.org_id == org_id,
                JiraTicket.pod != bt.pod,
                JiraTicket.is_deleted == False,
                JiraTicket.pod != None,
            ).distinct().all()

            for (dep_pod,) in sprint_mates:
                key = (bt.pod, dep_pod, bt.jira_key)
                if key not in seen:
                    seen.add(key)
                    deps.append({
                        "from_pod":           bt.pod,
                        "to_pod":             dep_pod,
                        "blocker_ticket_key": bt.jira_key,
                        "blocker_summary":    (bt.summary or "")[:80],
                        "impact_score":       _blocker_impact(bt),
                    })

        # Find pods sharing the same client (same client delivery = dependency)
        if bt.client:
            client_pods = db.query(JiraTicket.pod).filter(
                JiraTicket.org_id == org_id,
                JiraTicket.client == bt.client,
                JiraTicket.pod != bt.pod,
                JiraTicket.is_deleted == False,
                JiraTicket.pod != None,
            ).distinct().all()

            for (dep_pod,) in client_pods[:3]:  # cap at 3 per ticket
                key = (bt.pod, dep_pod, bt.jira_key)
                if key not in seen:
                    seen.add(key)
                    deps.append({
                        "from_pod":           bt.pod,
                        "to_pod":             dep_pod,
                        "blocker_ticket_key": bt.jira_key,
                        "blocker_summary":    (bt.summary or "")[:80],
                        "impact_score":       _blocker_impact(bt),
                    })

    deps.sort(key=lambda d: d["impact_score"], reverse=True)
    return deps


def _blocker_impact(ticket) -> int:
    """Simple impact score for a blocker ticket (0-100)."""
    score = 50
    p = (ticket.priority or "").lower()
    if p in ("critical", "blocker", "highest"): score += 40
    elif p == "high":                           score += 20
    elif p in ("low", "lowest", "trivial"):     score -= 20
    if ticket.story_points and ticket.story_points >= 5: score += 10
    return min(100, max(0, score))


@router.get("/{pod}/health")
async def get_space_health(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Unified health score for a single pod.
    Used by BOTH the Spaces list card and SummaryTab radar chart
    so they always show the same numbers.
    """
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint
    from app.services.health_service import compute_health

    org_id = user.org_id

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
    ).all()

    active_sprint = db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.pod == pod,
        Sprint.status == "active",
    ).first()

    if not tickets and not active_sprint:
        from fastapi import HTTPException
        raise HTTPException(404, f"No data found for pod '{pod}'")

    return compute_health(tickets, active_sprint)


@router.get("/{pod}/project")
async def get_space_project(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.ticket import JiraTicket, Worklog
    from app.models.sprint import Sprint
    from app.models.epic import Epic

    org_id = user.org_id

    # ── Pod stats (like analytics/pod-summary but single pod) ──
    status_rows = db.query(
        JiraTicket.status,
        func.count(JiraTicket.id).label("count"),
    ).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
    ).group_by(JiraTicket.status).all()

    statuses = {row.status or "—": row.count for row in status_rows}
    total_tickets = sum(statuses.values())
    done_keys = {"Done", "Closed", "Resolved"}
    in_prog_keys = {"In Progress", "In Development", "Development Ready"}
    blocked_keys = {"Blocked"}
    completed_tickets = sum(statuses.get(k, 0) for k in done_keys)
    in_progress_tickets = sum(statuses.get(k, 0) for k in in_prog_keys)
    blocked_tickets = sum(statuses.get(k, 0) for k in blocked_keys)
    progress = round((completed_tickets / total_tickets) * 100) if total_tickets else 0

    # Total hours for pod
    total_hours_row = db.query(
        func.sum(Worklog.hours).label("total_hours"),
    ).join(
        JiraTicket, JiraTicket.id == Worklog.ticket_id
    ).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
    ).first()
    total_hours = round(float(total_hours_row.total_hours or 0), 2) if total_hours_row else 0

    # ── Members derived from assignees ──
    assignees = db.query(
        JiraTicket.assignee,
        func.count(JiraTicket.id).label("ticket_count"),
    ).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
        JiraTicket.assignee != None,
    ).group_by(JiraTicket.assignee).order_by(func.count(JiraTicket.id).desc()).all()

    members = []
    for i, (name, _cnt) in enumerate(assignees):
        members.append({
            "id": f"m-{pod}-{i}",
            "name": name,
            "role": "Team Member",
            "initials": _initials(name),
            "color": _hash_color(name),
        })

    lead = members[0]["name"] if members else ""

    # ── Sprints for pod with nested tickets ──
    sprints = db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.pod == pod,
    ).order_by(Sprint.created_at.desc()).all()

    sprint_ids = [sp.id for sp in sprints]
    sprint_ticket_map = {sid: [] for sid in sprint_ids}

    if sprint_ids:
        tickets = db.query(JiraTicket).filter(
            JiraTicket.sprint_id.in_(sprint_ids),
            JiraTicket.is_deleted == False,
        ).all()
        for t in tickets:
            if t.sprint_id in sprint_ticket_map:
                sprint_ticket_map[t.sprint_id].append(t)

    project_sprints = []
    for sp in sprints:
        sp_tickets = sprint_ticket_map.get(sp.id, [])
        done_pts = sum(t.story_points or 0 for t in sp_tickets if _normalize_status(t.status) == "Done")
        total_pts = sum(t.story_points or 0 for t in sp_tickets)
        project_sprints.append({
            "id": sp.id,
            "name": sp.name,
            "status": sp.status,
            "startDate": sp.start_date.isoformat() if sp.start_date else "",
            "endDate": sp.end_date.isoformat() if sp.end_date else "",
            "goal": sp.goal or "",
            "totalPoints": total_pts,
            "donePoints": done_pts,
            "tasks": [
                {
                    "id": t.id,
                    "key": t.jira_key,
                    "title": t.summary,
                    "status": _normalize_status(t.status),
                    "priority": _normalize_priority(t.priority),
                    "type": _normalize_type(t.issue_type),
                    "assignee": t.assignee,
                    "assigneeInitials": _initials(t.assignee),
                    "assigneeColor": _hash_color(t.assignee or str(idx)),
                    "storyPoints": t.story_points or 0,
                    "dueDate": t.due_date.isoformat() if t.due_date else None,
                    "createdAt": t.jira_created.isoformat() if t.jira_created else "",
                    "updatedAt": t.jira_updated.isoformat() if t.jira_updated else "",
                    "description": t.description or f"{t.summary} — detailed description.",
                    "labels": [],
                    "sprint": sp.id,
                    "epicId": t.epic_id,
                }
                for idx, t in enumerate(sp_tickets)
            ],
        })

    # ── Epics for pod ──
    epics = db.query(Epic).filter(
        Epic.org_id == org_id,
        Epic.pod == pod,
    ).order_by(Epic.created_at.desc()).all()

    project_epics = [
        {
            "id": e.id,
            "title": e.title,
            "color": e.color or "#4F7EFF",
            "startDate": e.start_date.isoformat() if e.start_date else "",
            "endDate": e.end_date.isoformat() if e.end_date else "",
            "progress": e.progress or 0,
            "tasks": e.task_count or 0,
            "completed": e.completed_count or 0,
        }
        for e in epics
    ]

    # ── Weekly activity (tickets created per day of week, last 7 days) ──
    today = date.today()
    week_start = today - timedelta(days=6)
    daily_counts = {i: 0 for i in range(7)}
    created_rows = db.query(
        func.extract("dow", JiraTicket.jira_created).label("dow"),
        func.count(JiraTicket.id).label("cnt"),
    ).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
        JiraTicket.jira_created >= week_start,
    ).group_by(func.extract("dow", JiraTicket.jira_created)).all()
    # Postgres dow: 0=Sun, 1=Mon... reorder to Mon-Sun
    mon_sun = [0] * 7
    for row in created_rows:
        dow = int(row.dow)
        idx = dow - 1 if dow > 0 else 6
        mon_sun[idx] = row.cnt
    weekly_activity = mon_sun

    # ── Backlog tickets (no sprint) ──
    backlog = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.sprint_id == None,
        JiraTicket.is_deleted == False,
    ).all()

    # Inject backlog tasks into a virtual sprint so tabs can consume them
    backlog_tasks = [
        {
            "id": t.id,
            "key": t.jira_key,
            "title": t.summary,
            "status": _normalize_status(t.status),
            "priority": _normalize_priority(t.priority),
            "type": _normalize_type(t.issue_type),
            "assignee": t.assignee,
            "assigneeInitials": _initials(t.assignee),
            "assigneeColor": _hash_color(t.assignee or str(idx)),
            "storyPoints": t.story_points or 0,
            "dueDate": t.jira_updated.isoformat() if t.jira_updated else None,
            "createdAt": t.jira_created.isoformat() if t.jira_created else "",
            "updatedAt": t.jira_updated.isoformat() if t.jira_updated else "",
            "description": t.description or f"{t.summary} — detailed description.",
            "labels": [],
            "sprint": "backlog",
            "epicId": t.epic_id,
        }
        for idx, t in enumerate(backlog)
    ]

    # Backlog tasks are returned separately so tabs can consume them without
    # polluting the sprint list used by Roadmap / ActiveSprints.

    # ── Assemble Project payload ──
    pod_color = POD_COLORS.get(pod, "#8B8FA8")
    return {
        "id": pod,
        "key": pod,
        "name": f"{pod} Pod",
        "description": f"{pod} engineering pod — {total_tickets} total tickets · {total_hours}h logged",
        "status": "active",
        "category": "Engineering",
        "color": pod_color,
        "lead": lead,
        "leadInitials": _initials(lead),
        "leadColor": _hash_color(lead),
        "members": members,
        "sprints": project_sprints,
        "epics": project_epics,
        "startDate": "2026-01-01",
        "progress": progress,
        "totalTickets": total_tickets,
        "completedTickets": completed_tickets,
        "inProgressTickets": in_progress_tickets,
        "blockedTickets": blocked_tickets,
        "priority": "high",
        "tags": [pod],
        "weeklyActivity": weekly_activity,
        "roles": ["admin", "engineering_manager", "tech_lead", "team_member"],
        "backlogTasks": backlog_tasks,
    }


@router.get("/{pod}/backlog")
async def get_space_backlog(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.ticket import JiraTicket

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == user.org_id,
        JiraTicket.pod == pod,
        JiraTicket.sprint_id == None,
        JiraTicket.is_deleted == False,
    ).order_by(JiraTicket.jira_updated.desc()).all()

    return [
        {
            "id": t.id,
            "key": t.jira_key,
            "title": t.summary,
            "status": _normalize_status(t.status),
            "priority": _normalize_priority(t.priority),
            "type": _normalize_type(t.issue_type),
            "assignee": t.assignee,
            "assigneeInitials": _initials(t.assignee),
            "assigneeColor": _hash_color(t.assignee or str(idx)),
            "storyPoints": t.story_points or 0,
            "dueDate": t.due_date.isoformat() if t.due_date else None,
            "createdAt": t.jira_created.isoformat() if t.jira_created else "",
            "updatedAt": t.jira_updated.isoformat() if t.jira_updated else "",
        }
        for idx, t in enumerate(tickets)
    ]


@router.get("/{pod}/epics")
async def get_space_epics(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.epic import Epic

    epics = db.query(Epic).filter(
        Epic.org_id == user.org_id,
        Epic.pod == pod,
    ).order_by(Epic.created_at.desc()).all()

    return [
        {
            "id": e.id,
            "title": e.title,
            "color": e.color or "#4F7EFF",
            "startDate": e.start_date.isoformat() if e.start_date else "",
            "endDate": e.end_date.isoformat() if e.end_date else "",
            "progress": e.progress or 0,
            "tasks": e.task_count or 0,
            "completed": e.completed_count or 0,
        }
        for e in epics
    ]


@router.post("")
async def create_space(
    payload: SpaceCreatePayload,
    db: Session = Depends(get_db),
    user = Depends(get_manager_up),
):
    """Create a new space by inserting a planning sprint for the POD."""
    from app.models.sprint import Sprint

    org_id = user.org_id
    pod = payload.key.strip().upper()
    if not pod:
        raise HTTPException(status_code=400, detail="Space key is required")

    existing = db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.pod == pod,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Space '{pod}' already exists")

    today = date.today()
    sprint = Sprint(
        org_id=org_id,
        name=f"{payload.name} — Sprint 1",
        goal=payload.description,
        pod=pod,
        status="planning",
        start_date=today,
        end_date=today + timedelta(days=14),
    )
    db.add(sprint)
    db.commit()
    return {"pod": pod, "name": payload.name, "status": "created"}


@router.delete("/{pod}")
async def delete_space(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_manager_up),
):
    """Delete a space and all associated data."""
    from app.models.ticket import JiraTicket, Worklog
    from app.models.sprint import Sprint
    from app.models.epic import Epic

    org_id = user.org_id

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
    ).all()
    ticket_ids = [t.id for t in tickets]

    if ticket_ids:
        db.query(Worklog).filter(
            Worklog.ticket_id.in_(ticket_ids),
        ).delete(synchronize_session=False)

        db.query(JiraTicket).filter(
            JiraTicket.org_id == org_id,
            JiraTicket.pod == pod,
        ).delete(synchronize_session=False)

    db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.pod == pod,
    ).delete(synchronize_session=False)

    db.query(Epic).filter(
        Epic.org_id == org_id,
        Epic.pod == pod,
    ).delete(synchronize_session=False)

    db.commit()
    return {"pod": pod, "status": "deleted"}
