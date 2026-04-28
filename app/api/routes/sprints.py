"""
app/api/routes/sprints.py — Sprint lifecycle management.

Endpoints:
  GET  /api/sprints               List sprints for org
  POST /api/sprints               Create sprint (PM+)
  GET  /api/sprints/:id           Get single sprint
  POST /api/sprints/:id/start     Start sprint → status=active, notify team
  POST /api/sprints/:id/complete  Complete sprint → move unfinished to backlog
  GET  /api/sprints/:id/burndown  Daily {date, ideal, actual} point series
  GET  /api/sprints/:id/velocity  Historical velocity [{sprint_name, points_completed}]
"""

from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tech_lead_up

router = APIRouter(prefix="/api/sprints", tags=["sprints"])


# ── Schemas ────────────────────────────────────────────────────────────────

class SprintCreate(BaseModel):
    name:        str
    goal:        Optional[str]       = None
    start_date:  Optional[date]      = None
    end_date:    Optional[date]      = None
    project_id:  Optional[str]       = None
    ticket_keys: Optional[List[str]] = None


class SprintStartBody(BaseModel):
    name:       Optional[str]  = None
    goal:       Optional[str]  = None
    start_date: Optional[date] = None
    end_date:   Optional[date] = None


class SprintOut(BaseModel):
    id:         str
    org_id:     str
    name:       str
    goal:       Optional[str]
    start_date: Optional[date]
    end_date:   Optional[date]
    status:     str
    velocity:   Optional[int]

    class Config:
        from_attributes = True


# ── Helpers ────────────────────────────────────────────────────────────────

def _create_notification(db, org_id: str, user_id: Optional[str], ntype: str, title: str, body: str, link: str = None):
    from app.models.notification import Notification
    from app.models.base import gen_uuid
    notif = Notification(
        id=gen_uuid(), org_id=org_id, user_id=user_id,
        type=ntype, title=title, body=body, link=link,
    )
    db.add(notif)


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_sprints(
    project_id: Optional[str] = Query(None),
    status:     Optional[str] = Query(None),
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket
    q = db.query(Sprint).filter(Sprint.org_id == user.org_id)
    if status:
        q = q.filter(Sprint.status == status)
    if project_id:
        q = q.filter(Sprint.pod == project_id)
    sprints = q.order_by(Sprint.created_at.desc()).all()

    # Bulk-load all tickets for these sprints — avoids N+1 (BUG-09)
    from collections import defaultdict
    sprint_ids = [sp.id for sp in sprints]
    all_tickets = db.query(JiraTicket).filter(
        JiraTicket.sprint_id.in_(sprint_ids),
        JiraTicket.is_deleted == False,
    ).all() if sprint_ids else []

    tickets_by_sprint: dict = defaultdict(list)
    for t in all_tickets:
        tickets_by_sprint[t.sprint_id].append(t)

    result = []
    for sp in sprints:
        tickets   = tickets_by_sprint[sp.id]
        done_pts  = sum(t.story_points or 0 for t in tickets if t.status == "Done")
        total_pts = sum(t.story_points or 0 for t in tickets)
        result.append({
            "id":              sp.id,
            "name":            sp.name,
            "goal":            sp.goal,
            "start_date":      sp.start_date.isoformat() if sp.start_date else None,
            "end_date":        sp.end_date.isoformat()   if sp.end_date   else None,
            "status":          sp.status,
            "velocity":        sp.velocity,
            "ticket_count":    len(tickets),
            "done_points":     done_pts,
            "total_points":    total_pts,
            "completion_pct":  round(done_pts / total_pts * 100) if total_pts else 0,
        })
    return result


@router.post("", status_code=201)
async def create_sprint(
    body: SprintCreate,
    db:   Session = Depends(get_db),
    user = Depends(get_tech_lead_up),
):
    from app.models.sprint import Sprint
    from app.models.base import gen_uuid

    # Validate dates before creating (BUG-18)
    if body.start_date and body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "end_date must be on or after start_date")

    sprint = Sprint(
        id=gen_uuid(),
        org_id=user.org_id,
        name=body.name,
        goal=body.goal,
        start_date=body.start_date,
        end_date=body.end_date,
        status="planning",
        pod=body.project_id,
    )
    db.add(sprint)
    db.commit()
    db.refresh(sprint)

    # Assign drafted tickets to the new sprint if provided
    if body.ticket_keys:
        from app.models.ticket import JiraTicket
        db.query(JiraTicket).filter(
            JiraTicket.org_id    == user.org_id,
            JiraTicket.jira_key.in_(body.ticket_keys),
            JiraTicket.is_deleted == False,
        ).update({"sprint_id": sprint.id}, synchronize_session=False)
        db.commit()

    return sprint


@router.get("/{sprint_id}")
async def get_sprint(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket

    sprint = db.query(Sprint).filter(
        Sprint.id == sprint_id, Sprint.org_id == user.org_id
    ).first()
    if not sprint:
        raise HTTPException(404, "Sprint not found")

    tickets = db.query(JiraTicket).filter(
        JiraTicket.sprint_id == sprint_id,
        JiraTicket.is_deleted == False,
    ).all()

    return {
        "id":         sprint.id,
        "name":       sprint.name,
        "goal":       sprint.goal,
        "start_date": sprint.start_date.isoformat() if sprint.start_date else None,
        "end_date":   sprint.end_date.isoformat()   if sprint.end_date   else None,
        "status":     sprint.status,
        "velocity":   sprint.velocity,
        "tickets":    [
            {
                "id":           t.id,
                "jira_key":     t.jira_key,
                "summary":      t.summary,
                "status":       t.status,
                "assignee":     t.assignee,
                "story_points": t.story_points,
                "issue_type":   t.issue_type,
                "priority":     t.priority,
            }
            for t in tickets
        ],
    }


@router.post("/{sprint_id}/start")
async def start_sprint(
    sprint_id: str,
    body: SprintStartBody = SprintStartBody(),
    db:   Session = Depends(get_db),
    user = Depends(get_tech_lead_up),
):
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket
    from app.models.user import User

    sprint = db.query(Sprint).filter(
        Sprint.id == sprint_id, Sprint.org_id == user.org_id
    ).first()
    if not sprint:
        raise HTTPException(404, "Sprint not found")
    if sprint.status != "planning":
        raise HTTPException(400, f"Sprint is already {sprint.status}")

    # Apply editable fields from the Start Sprint modal (BUG-08)
    if body.name and body.name.strip():
        sprint.name = body.name.strip()
    if body.goal is not None:
        sprint.goal = body.goal
    if body.end_date:
        sprint.end_date = body.end_date

    sprint.status = "active"
    sprint.start_date = body.start_date or sprint.start_date or date.today()

    # Notify all members assigned tickets in this sprint
    assignees = db.query(JiraTicket.assignee_email).filter(
        JiraTicket.sprint_id  == sprint_id,
        JiraTicket.is_deleted == False,
        JiraTicket.assignee_email != None,
    ).distinct().all()

    for (email,) in assignees:
        member = db.query(User).filter(
            User.email == email, User.org_id == user.org_id
        ).first()
        if member:
            _create_notification(
                db, user.org_id, member.id,
                "sprint_started",
                f"Sprint '{sprint.name}' has started!",
                f"The sprint you have tickets in has started. Check your assignments.",
                f"/sprints/{sprint_id}",
            )

    db.commit()
    # Automation hook
    from app.services.automation_engine import run_automations
    await run_automations("sprint_started", {"sprint_id": sprint_id, "sprint_name": sprint.name}, user.org_id, sprint.pod or "", db)
    return {"message": "Sprint started", "sprint_id": sprint_id, "status": "active"}


@router.post("/{sprint_id}/complete")
async def complete_sprint(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user = Depends(get_tech_lead_up),
):
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket

    sprint = db.query(Sprint).filter(
        Sprint.id == sprint_id, Sprint.org_id == user.org_id
    ).first()
    if not sprint:
        raise HTTPException(404, "Sprint not found")
    if sprint.status != "active":
        raise HTTPException(400, "Only active sprints can be completed")

    # Move incomplete tickets to backlog
    incomplete = db.query(JiraTicket).filter(
        JiraTicket.sprint_id  == sprint_id,
        JiraTicket.status     != "Done",
        JiraTicket.is_deleted == False,
    ).all()
    for t in incomplete:
        t.sprint_id = None
        t.status    = "Backlog"

    # Calculate velocity
    done_pts = db.query(JiraTicket).filter(
        JiraTicket.sprint_id  == sprint_id,
        JiraTicket.status     == "Done",
        JiraTicket.is_deleted == False,
    ).all()
    sprint.velocity = sum(t.story_points or 0 for t in done_pts)
    sprint.status   = "completed"
    if not sprint.end_date:
        sprint.end_date = date.today()

    db.commit()
    # Automation hook
    from app.services.automation_engine import run_automations
    await run_automations("sprint_completed", {"sprint_id": sprint_id, "sprint_name": sprint.name, "velocity": sprint.velocity}, user.org_id, sprint.pod or "", db)
    return {
        "message":          "Sprint completed",
        "sprint_id":        sprint_id,
        "velocity":         sprint.velocity,
        "moved_to_backlog": len(incomplete),
    }


@router.delete("/{sprint_id}", status_code=200)
async def delete_sprint(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user = Depends(get_tech_lead_up),
):
    """Delete a sprint that is still in planning status. Tickets are moved back to backlog."""
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket

    sprint = db.query(Sprint).filter(
        Sprint.id == sprint_id, Sprint.org_id == user.org_id
    ).first()
    if not sprint:
        raise HTTPException(404, "Sprint not found")
    if sprint.status != "planning":
        raise HTTPException(400, "Only planning sprints can be deleted")

    # Unassign all tickets — move them back to backlog
    db.query(JiraTicket).filter(
        JiraTicket.sprint_id  == sprint_id,
        JiraTicket.is_deleted == False,
    ).update({"sprint_id": None}, synchronize_session=False)

    db.delete(sprint)
    db.commit()
    return {"message": f"Sprint '{sprint.name}' deleted", "sprint_id": sprint_id}


@router.post("/{sprint_id}/tickets", status_code=200)
async def add_ticket_to_sprint(
    sprint_id: str,
    body: dict,
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Assign a ticket to this sprint by ticket_key."""
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket

    sprint = db.query(Sprint).filter(
        Sprint.id == sprint_id, Sprint.org_id == user.org_id
    ).first()
    if not sprint:
        raise HTTPException(404, "Sprint not found")

    ticket_key = body.get("ticket_key")
    if not ticket_key:
        raise HTTPException(400, "ticket_key is required")

    ticket = db.query(JiraTicket).filter(
        JiraTicket.jira_key == ticket_key,
        JiraTicket.org_id   == user.org_id,
        JiraTicket.is_deleted == False,
    ).first()
    if not ticket:
        raise HTTPException(404, f"Ticket '{ticket_key}' not found")

    # Prevent cross-pod assignment (BUG-19)
    if sprint.pod and ticket.pod and sprint.pod != ticket.pod:
        raise HTTPException(400, f"Ticket '{ticket_key}' belongs to pod '{ticket.pod}', not '{sprint.pod}'")

    ticket.sprint_id = sprint_id
    db.commit()
    return {"message": f"Ticket {ticket_key} added to sprint {sprint_id}"}


@router.delete("/{sprint_id}/tickets/{ticket_key}", status_code=200)
async def remove_ticket_from_sprint(
    sprint_id:  str,
    ticket_key: str,
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Remove a ticket from this sprint (sets sprint_id = None)."""
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket

    sprint = db.query(Sprint).filter(
        Sprint.id == sprint_id, Sprint.org_id == user.org_id
    ).first()
    if not sprint:
        raise HTTPException(404, "Sprint not found")

    ticket = db.query(JiraTicket).filter(
        JiraTicket.jira_key  == ticket_key,
        JiraTicket.org_id    == user.org_id,
        JiraTicket.sprint_id == sprint_id,
        JiraTicket.is_deleted == False,
    ).first()
    if not ticket:
        raise HTTPException(404, f"Ticket '{ticket_key}' not found in this sprint")

    ticket.sprint_id = None
    db.commit()
    return {"message": f"Ticket {ticket_key} removed from sprint {sprint_id}"}


@router.get("/{sprint_id}/burndown")
async def sprint_burndown(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket, Worklog

    sprint = db.query(Sprint).filter(
        Sprint.id == sprint_id, Sprint.org_id == user.org_id
    ).first()
    if not sprint:
        raise HTTPException(404, "Sprint not found")
    if not sprint.start_date or not sprint.end_date:
        raise HTTPException(400, "Sprint dates not set")

    tickets = db.query(JiraTicket).filter(
        JiraTicket.sprint_id  == sprint_id,
        JiraTicket.is_deleted == False,
    ).all()

    total_pts = sum(t.story_points or 0 for t in tickets)
    start     = sprint.start_date
    end       = sprint.end_date
    days      = (end - start).days + 1
    if days < 1:
        days = 1

    # Build daily ideal burndown
    burndown = []
    for i in range(days):
        day         = start + timedelta(days=i)
        ideal_left  = round(total_pts * (1 - i / (days - 1))) if days > 1 else 0

        # Actual: count points remaining as of this date
        # (simplified: uses done tickets' synced_at date)
        done_by_day = sum(
            t.story_points or 0
            for t in tickets
            if t.status == "Done" and t.synced_at and t.synced_at.date() <= day
        )
        actual_left = max(0, total_pts - done_by_day)

        burndown.append({
            "date":   day.isoformat(),
            "ideal":  ideal_left,
            "actual": actual_left,
        })

    return {
        "sprint_id":   sprint_id,
        "sprint_name": sprint.name,
        "total_points": total_pts,
        "data": burndown,
    }


@router.get("/{sprint_id}/velocity")
async def sprint_velocity(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Return velocity history for the org (last 10 completed sprints)."""
    from app.models.sprint import Sprint

    sprints = db.query(Sprint).filter(
        Sprint.org_id  == user.org_id,
        Sprint.status  == "completed",
        Sprint.velocity != None,
    ).order_by(Sprint.end_date.desc()).limit(10).all()

    return [
        {
            "sprint_id":         s.id,
            "sprint_name":       s.name,
            "points_completed":  s.velocity,
            "end_date":          s.end_date.isoformat() if s.end_date else None,
        }
        for s in reversed(sprints)
    ]
