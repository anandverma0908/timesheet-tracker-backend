"""
app/api/routes/spaces.py — Project/Space detail aggregation for the Spaces feature.

Endpoints:
  GET    /api/spaces                       List all spaces with health scores
  GET    /api/spaces/{pod}/project         Full project payload (matches frontend Project type)
  GET    /api/spaces/{pod}/health          Unified health score + radar + risk flags
  GET    /api/spaces/anomalies             Rule-based anomaly detection across all pods
  GET    /api/spaces/dependencies          Cross-space blocker dependency map
  GET    /api/spaces/{pod}/backlog         Tickets in this pod not assigned to any sprint
  GET    /api/spaces/{pod}/epics           Epics for this pod
  POST   /api/spaces                       Create a new space (with optional member_ids)
  DELETE /api/spaces/{pod}                 Delete a space and all its data
  GET    /api/spaces/{pod}/members         List space members
  POST   /api/spaces/{pod}/members         Add a member to a space
  DELETE /api/spaces/{pod}/members/{uid}   Remove a member from a space
"""

from datetime import date, timedelta, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_manager_up

router = APIRouter(prefix="/api/spaces", tags=["spaces"])


from typing import List as _List

class SpaceCreatePayload(BaseModel):
    key: str
    name: str
    description: str
    category: str
    color: str
    member_ids: _List[str] = []


class AddMemberPayload(BaseModel):
    user_id: str
    role: str = "member"


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

    # ── Members from space_members table ──
    from app.models.space_member import SpaceMember
    from app.models.user import User as UserModel

    space_member_rows = db.query(SpaceMember).filter(
        SpaceMember.org_id == org_id,
        SpaceMember.pod == pod,
    ).all()

    members = []
    for sm in space_member_rows:
        u = sm.user
        if not u:
            continue
        members.append({
            "id":       u.id,
            "name":     u.name,
            "email":    u.email,
            "role":     sm.role.capitalize(),
            "initials": _initials(u.name),
            "color":    _hash_color(u.name),
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
                    "description": t.description or "",
                    "labels": t.labels or [],
                    "sprint": sp.id,
                    "epicId": t.epic_id,
                    "parentId": t.parent_id,
                    "pod": t.pod,
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
            "dueDate": t.due_date.isoformat() if t.due_date else None,
            "createdAt": t.jira_created.isoformat() if t.jira_created else "",
            "updatedAt": t.jira_updated.isoformat() if t.jira_updated else "",
            "description": t.description or "",
            "labels": t.labels or [],
            "sprint": "backlog",
            "epicId": t.epic_id,
            "pod": t.pod,
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
    """Create a new space with an initial sprint and assign members."""
    from app.models.sprint import Sprint
    from app.models.space_member import SpaceMember
    from app.models.user import User as UserModel

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

    # Assign members — first member becomes lead
    seen = set()
    for i, uid in enumerate(payload.member_ids):
        if uid in seen:
            continue
        seen.add(uid)
        u = db.query(UserModel).filter(UserModel.id == uid, UserModel.org_id == org_id).first()
        if not u:
            continue
        db.add(SpaceMember(
            org_id=org_id,
            pod=pod,
            user_id=uid,
            role="lead" if i == 0 else "member",
        ))

    db.commit()
    return {"pod": pod, "name": payload.name, "status": "created", "member_count": len(seen)}


@router.get("/{pod}/members")
async def list_space_members(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """List all members of a space."""
    from app.models.space_member import SpaceMember

    rows = db.query(SpaceMember).filter(
        SpaceMember.org_id == user.org_id,
        SpaceMember.pod == pod,
    ).all()

    return [
        {
            "id":       sm.user.id,
            "name":     sm.user.name,
            "email":    sm.user.email,
            "role":     sm.role,
            "initials": _initials(sm.user.name),
            "color":    _hash_color(sm.user.name),
        }
        for sm in rows if sm.user
    ]


@router.post("/{pod}/members")
async def add_space_member(
    pod: str,
    body: AddMemberPayload,
    db: Session = Depends(get_db),
    user = Depends(get_manager_up),
):
    """Add a user to a space."""
    from app.models.space_member import SpaceMember
    from app.models.user import User as UserModel

    u = db.query(UserModel).filter(UserModel.id == body.user_id, UserModel.org_id == user.org_id).first()
    if not u:
        raise HTTPException(404, "User not found")

    existing = db.query(SpaceMember).filter(
        SpaceMember.org_id == user.org_id,
        SpaceMember.pod == pod,
        SpaceMember.user_id == body.user_id,
    ).first()
    if existing:
        existing.role = body.role
        db.commit()
        return {"status": "updated"}

    db.add(SpaceMember(org_id=user.org_id, pod=pod, user_id=body.user_id, role=body.role))
    db.commit()
    return {"status": "added"}


@router.delete("/{pod}/members/{user_id}")
async def remove_space_member(
    pod: str,
    user_id: str,
    db: Session = Depends(get_db),
    user = Depends(get_manager_up),
):
    """Remove a user from a space."""
    from app.models.space_member import SpaceMember

    row = db.query(SpaceMember).filter(
        SpaceMember.org_id == user.org_id,
        SpaceMember.pod == pod,
        SpaceMember.user_id == user_id,
    ).first()
    if not row:
        raise HTTPException(404, "Member not found")

    db.delete(row)
    db.commit()
    return {"status": "removed"}


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


# ═══════════════════════════════════════════════════════════════════════════════
#  Reports
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{pod}/reports/burndown")
async def get_burndown_report(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Burndown for the active sprint in this pod.
    Returns daily remaining story points vs ideal line.
    """
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket
    from app.models.audit import AuditLog
    from datetime import datetime

    org_id = user.org_id
    sprint = db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.pod == pod,
        Sprint.status == "active",
    ).order_by(Sprint.start_date.desc()).first()

    if not sprint or not sprint.start_date or not sprint.end_date:
        return {"sprint": None, "data": []}

    tickets = db.query(JiraTicket).filter(
        JiraTicket.sprint_id == sprint.id,
        JiraTicket.is_deleted == False,
    ).all()

    total_pts = sum((t.story_points or 0) for t in tickets)
    ticket_ids = [t.id for t in tickets]

    # Find done transitions from audit log
    done_audits = db.query(AuditLog).filter(
        AuditLog.org_id == org_id,
        AuditLog.entity_type == "ticket",
        AuditLog.entity_id.in_(ticket_ids),
        AuditLog.action == "status_changed",
    ).order_by(AuditLog.created_at).all()

    done_map = {}  # ticket_id -> date_str when transitioned to Done
    for a in done_audits:
        diff = a.diff_json or {}
        if diff.get("new") in ("Done", "Closed", "Resolved"):
            d = a.created_at.date().isoformat()
            done_map[str(a.entity_id)] = d

    start = sprint.start_date
    end = sprint.end_date
    total_days = max(1, (end - start).days)
    today = date.today()
    days = []
    for i in range(total_days + 1):
        d = start + timedelta(days=i)
        if d > today:
            break
        days.append(d)

    data = []
    for d in days:
        ds = d.isoformat()
        done_pts = sum(
            (t.story_points or 0)
            for t in tickets
            if done_map.get(str(t.id), "9999-99-99") <= ds
        )
        remaining = total_pts - done_pts
        ideal = total_pts * (1 - (d - start).days / total_days)
        data.append({"date": ds, "remaining": remaining, "ideal": round(ideal, 1)})

    return {"sprint": {"id": sprint.id, "name": sprint.name, "total_points": total_pts}, "data": data}


@router.get("/{pod}/reports/velocity")
async def get_velocity_report(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Velocity for the last 8 completed sprints in this pod.
    """
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket

    org_id = user.org_id
    sprints = db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.pod == pod,
        Sprint.status == "completed",
    ).order_by(Sprint.end_date.desc()).limit(8).all()

    result = []
    for sp in reversed(sprints):
        tickets = db.query(JiraTicket).filter(
            JiraTicket.sprint_id == sp.id,
            JiraTicket.is_deleted == False,
        ).all()
        committed = sum((t.story_points or 0) for t in tickets)
        completed = sum((t.story_points or 0) for t in tickets if _normalize_status(t.status) == "Done")
        result.append({
            "sprint": sp.name,
            "committed": committed,
            "completed": completed,
            "start_date": sp.start_date.isoformat() if sp.start_date else "",
            "end_date": sp.end_date.isoformat() if sp.end_date else "",
        })
    return result


@router.get("/{pod}/reports/cfd")
async def get_cfd_report(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Cumulative Flow Diagram for the last 30 days.
    Returns daily ticket counts by status.
    """
    from app.models.ticket import JiraTicket
    from app.models.audit import AuditLog
    from datetime import datetime

    org_id = user.org_id
    today = date.today()
    start_date = today - timedelta(days=29)

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
    ).all()

    ticket_ids = [t.id for t in tickets]

    # Get all status change audits for these tickets in the window
    audits = db.query(AuditLog).filter(
        AuditLog.org_id == org_id,
        AuditLog.entity_type == "ticket",
        AuditLog.entity_id.in_(ticket_ids),
        AuditLog.action == "status_changed",
        AuditLog.created_at >= datetime.combine(start_date, datetime.min.time()),
    ).order_by(AuditLog.created_at).all()

    # Build a history map: ticket_id -> list of (date, status)
    history = {}
    for t in tickets:
        history[str(t.id)] = [(start_date, _normalize_status(t.status))]

    for a in audits:
        diff = a.diff_json or {}
        new_status = _normalize_status(diff.get("new"))
        d = a.created_at.date()
        tid = str(a.entity_id)
        if tid in history:
            history[tid].append((d, new_status))
            history[tid].sort(key=lambda x: x[0])

    # For each day, determine status of each ticket
    statuses = ["To Do", "In Progress", "In Review", "Blocked", "Done"]
    data = []
    for i in range(30):
        d = start_date + timedelta(days=i)
        counts = {s: 0 for s in statuses}
        for tid, events in history.items():
            # find most recent status on or before d
            current = events[0][1]
            for ed, es in events:
                if ed <= d:
                    current = es
                else:
                    break
            if current in counts:
                counts[current] += 1
        row = {"date": d.isoformat()}
        for s in statuses:
            row[s] = counts[s]
        data.append(row)

    return data


# ═══════════════════════════════════════════════════════════════════════════════
#  Epic CRUD
# ═══════════════════════════════════════════════════════════════════════════════

class EpicCreatePayload(BaseModel):
    title: str
    color: Optional[str] = "#4F7EFF"
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class EpicUpdatePayload(BaseModel):
    title: Optional[str] = None
    color: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@router.post("/{pod}/epics")
async def create_epic(
    pod: str,
    payload: EpicCreatePayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.epic import Epic
    from app.models.base import gen_uuid
    from datetime import datetime

    epic = Epic(
        id=gen_uuid(),
        org_id=user.org_id,
        pod=pod,
        title=payload.title,
        color=payload.color,
        start_date=datetime.strptime(payload.start_date, "%Y-%m-%d").date() if payload.start_date else None,
        end_date=datetime.strptime(payload.end_date, "%Y-%m-%d").date() if payload.end_date else None,
        progress=0,
        task_count=0,
        completed_count=0,
    )
    db.add(epic)
    db.commit()
    db.refresh(epic)
    return {
        "id": epic.id,
        "title": epic.title,
        "color": epic.color or "#4F7EFF",
        "startDate": epic.start_date.isoformat() if epic.start_date else "",
        "endDate": epic.end_date.isoformat() if epic.end_date else "",
        "progress": epic.progress or 0,
        "tasks": epic.task_count or 0,
        "completed": epic.completed_count or 0,
    }


@router.put("/{pod}/epics/{epic_id}")
async def update_epic(
    pod: str,
    epic_id: str,
    payload: EpicUpdatePayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.epic import Epic
    from datetime import datetime

    epic = db.query(Epic).filter(
        Epic.id == epic_id,
        Epic.org_id == user.org_id,
        Epic.pod == pod,
    ).first()
    if not epic:
        raise HTTPException(404, "Epic not found")

    if payload.title is not None:
        epic.title = payload.title
    if payload.color is not None:
        epic.color = payload.color
    if payload.start_date is not None:
        epic.start_date = datetime.strptime(payload.start_date, "%Y-%m-%d").date()
    if payload.end_date is not None:
        epic.end_date = datetime.strptime(payload.end_date, "%Y-%m-%d").date()

    db.commit()
    db.refresh(epic)
    return {
        "id": epic.id,
        "title": epic.title,
        "color": epic.color or "#4F7EFF",
        "startDate": epic.start_date.isoformat() if epic.start_date else "",
        "endDate": epic.end_date.isoformat() if epic.end_date else "",
        "progress": epic.progress or 0,
        "tasks": epic.task_count or 0,
        "completed": epic.completed_count or 0,
    }


@router.delete("/{pod}/epics/{epic_id}", status_code=204)
async def delete_epic(
    pod: str,
    epic_id: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.epic import Epic
    from app.models.ticket import JiraTicket

    epic = db.query(Epic).filter(
        Epic.id == epic_id,
        Epic.org_id == user.org_id,
        Epic.pod == pod,
    ).first()
    if not epic:
        raise HTTPException(404, "Epic not found")

    # Unlink tickets
    db.query(JiraTicket).filter(
        JiraTicket.epic_id == epic_id,
    ).update({"epic_id": None}, synchronize_session=False)

    db.delete(epic)
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
#  Board Config
# ═══════════════════════════════════════════════════════════════════════════════

class BoardConfigPayload(BaseModel):
    columns: list
    swimlane_by: Optional[str] = None
    wip_limits: dict = {}


@router.get("/{pod}/board-config")
async def get_board_config(
    pod: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.board_config import BoardConfig
    config = db.query(BoardConfig).filter(
        BoardConfig.org_id == user.org_id,
        BoardConfig.pod == pod,
    ).first()
    if not config:
        return {
            "columns": [
                {"id": "todo", "name": "To Do", "status_mapping": ["To Do"]},
                {"id": "in_progress", "name": "In Progress", "status_mapping": ["In Progress"]},
                {"id": "in_review", "name": "In Review", "status_mapping": ["In Review"]},
                {"id": "blocked", "name": "Blocked", "status_mapping": ["Blocked"]},
                {"id": "done", "name": "Done", "status_mapping": ["Done"]},
            ],
            "swimlane_by": "none",
            "wip_limits": {},
        }
    return {
        "columns": config.columns or [],
        "swimlane_by": config.swimlane_by or "none",
        "wip_limits": config.wip_limits or {},
    }


@router.put("/{pod}/board-config")
async def update_board_config(
    pod: str,
    payload: BoardConfigPayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.board_config import BoardConfig
    from app.models.base import gen_uuid

    config = db.query(BoardConfig).filter(
        BoardConfig.org_id == user.org_id,
        BoardConfig.pod == pod,
    ).first()

    if config:
        config.columns = payload.columns
        config.swimlane_by = payload.swimlane_by
        config.wip_limits = payload.wip_limits
    else:
        config = BoardConfig(
            id=gen_uuid(),
            org_id=user.org_id,
            pod=pod,
            columns=payload.columns,
            swimlane_by=payload.swimlane_by,
            wip_limits=payload.wip_limits,
        )
        db.add(config)

    db.commit()
    db.refresh(config)
    return {
        "columns": config.columns or [],
        "swimlane_by": config.swimlane_by or "none",
        "wip_limits": config.wip_limits or {},
    }


@router.get("/{pod}/stories")
async def get_pod_stories(
    pod: str,
    sprint_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """
    Stories in the active (or given) sprint for a pod.
    Each story includes its child tasks, progress, and a rule-based EOS insight.
    """
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint
    from datetime import date as _date

    org_id = user.org_id
    DONE = {"Done", "Closed", "Resolved"}

    if sprint_id:
        sprint = db.query(Sprint).filter(
            Sprint.id == sprint_id, Sprint.org_id == org_id,
        ).first()
    else:
        sprint = db.query(Sprint).filter(
            Sprint.org_id == org_id, Sprint.pod == pod, Sprint.status == "active",
        ).first()
        if not sprint:
            sprint = db.query(Sprint).filter(
                Sprint.org_id == org_id, Sprint.pod == pod, Sprint.status == "planning",
            ).order_by(Sprint.created_at.desc()).first()

    if not sprint:
        return {"stories": [], "sprint_id": None, "everything_else": {"totalTasks": 0, "doneTasks": 0, "tasks": []}}

    sprint_tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.sprint_id == sprint.id,
        JiraTicket.is_deleted == False,
    ).all()

    stories = [t for t in sprint_tickets if (t.issue_type or "").lower() == "story"]
    ticket_by_id = {t.id: t for t in sprint_tickets}
    child_map: dict = {}
    for t in sprint_tickets:
        if t.parent_id and t.parent_id in ticket_by_id:
            child_map.setdefault(t.parent_id, []).append(t)

    today = _date.today()

    def _eos_insight(story, children: list) -> dict:
        total = len(children)
        done_count = sum(1 for c in children if _normalize_status(c.status) == "Done")
        blocked = sum(1 for c in children if _normalize_status(c.status) == "Blocked")
        in_progress = sum(1 for c in children if _normalize_status(c.status) == "In Progress")
        pct = round((done_count / total) * 100) if total > 0 else 0
        stale_days = (today - story.jira_updated).days if story.jira_updated else 0
        days_left = max(0, (sprint.end_date - today).days) if sprint.end_date else 7

        if blocked > 0:
            return {"label": "Blocked", "color": "red",
                    "text": f"{blocked} task{'s' if blocked > 1 else ''} blocked — needs immediate attention."}
        if total == 0:
            return {"label": "No Tasks", "color": "amber", "text": "No tasks linked yet."}
        if pct == 100:
            return {"label": "Complete", "color": "green", "text": "All tasks done. Ready to close."}
        if stale_days > 5 and pct < 50:
            return {"label": "Stale", "color": "amber",
                    "text": f"No activity for {stale_days}d and only {pct}% complete."}
        if days_left <= 2 and pct < 70:
            return {"label": "At Risk", "color": "red",
                    "text": f"Only {pct}% done with {days_left}d left in sprint."}
        if in_progress > 0 and pct >= 50:
            return {"label": "On Track", "color": "green", "text": f"{pct}% complete — progressing well."}
        return {"label": "In Progress", "color": "accent",
                "text": f"{done_count}/{total} tasks done ({pct}%)."}

    def _serialize_task(t) -> dict:
        return {
            "id": t.id, "key": t.jira_key, "title": t.summary,
            "status": _normalize_status(t.status),
            "priority": _normalize_priority(t.priority),
            "type": _normalize_type(t.issue_type),
            "assignee": t.assignee,
            "assigneeInitials": _initials(t.assignee),
            "assigneeColor": _hash_color(t.assignee or t.id),
            "storyPoints": t.story_points or 0,
            "dueDate": t.due_date.isoformat() if t.due_date else None,
            "createdAt": t.jira_created.isoformat() if t.jira_created else "",
            "updatedAt": t.jira_updated.isoformat() if t.jira_updated else "",
            "description": t.description or "",
            "labels": t.labels or [],
            "sprint": sprint.id,
            "epicId": t.epic_id,
            "parentId": t.parent_id,
            "pod": t.pod,
        }

    result = []
    for story in stories:
        children = child_map.get(story.id, [])
        total = len(children)
        done_count = sum(1 for c in children if _normalize_status(c.status) == "Done")
        blocked = sum(1 for c in children if _normalize_status(c.status) == "Blocked")
        pct = round((done_count / total) * 100) if total > 0 else 0
        result.append({
            "id": story.id, "key": story.jira_key, "title": story.summary,
            "status": _normalize_status(story.status),
            "priority": _normalize_priority(story.priority),
            "assignee": story.assignee,
            "assigneeInitials": _initials(story.assignee),
            "assigneeColor": _hash_color(story.assignee or story.id),
            "epicId": story.epic_id,
            "storyPoints": story.story_points or 0,
            "totalTasks": total, "doneTasks": done_count,
            "blockedTasks": blocked, "progressPct": pct,
            "eosInsight": _eos_insight(story, children),
            "tasks": [_serialize_task(c) for c in children],
        })

    story_ids = {s.id for s in stories}
    unlinked = [
        t for t in sprint_tickets
        if (t.issue_type or "").lower() != "story"
        and (not t.parent_id or t.parent_id not in story_ids)
    ]
    unlinked_done = sum(1 for t in unlinked if _normalize_status(t.status) == "Done")

    return {
        "sprint_id": sprint.id,
        "sprint_name": sprint.name,
        "stories": result,
        "everything_else": {
            "totalTasks": len(unlinked),
            "doneTasks": unlinked_done,
            "tasks": [_serialize_task(t) for t in unlinked],
        },
    }
