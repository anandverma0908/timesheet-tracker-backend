"""
app/api/routes/tickets.py — Full ticket CRUD + NL create + AI analyze + comments + attachments.

Endpoints:
  POST   /api/tickets                    Create ticket
  GET    /api/tickets                    List tickets (filtered)
  GET    /api/tickets/:id                Get single ticket
  PUT    /api/tickets/:id                Update ticket
  DELETE /api/tickets/:id                Soft delete
  POST   /api/tickets/:id/status         Status transition + audit log
  POST   /api/tickets/nl-create          NL → AI analysis → create
  POST   /api/tickets/ai-analyze         NL → AI analysis (no create)
  GET    /api/tickets/:id/comments       List comments
  POST   /api/tickets/:id/comments       Add comment
  DELETE /api/tickets/:id/comments/:cid  Soft-delete comment
  POST   /api/tickets/:id/attachments    Upload attachment
  GET    /api/tickets/:id/attachments    List attachments
  GET    /api/tickets/:id/worklogs       List worklogs
  POST   /api/tickets/:id/worklogs       Log time
  GET    /api/tickets/:id/links          List linked issues
  POST   /api/tickets/:id/links          Add link
  DELETE /api/tickets/:id/links/:lid     Remove link
  GET    /api/tickets/:id/activity       Audit log for ticket
"""

import os
import uuid
from typing import Optional, List, Dict

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.dependencies import get_current_user, get_visibility_scope, VisibilityScope
from app.core.config import settings
from app.models.ticket import JiraTicket, TicketComment, TicketAttachment, TicketLink
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.ticket import (
    TicketCreate, TicketUpdate, TicketOut, StatusTransition,
    NLCreateRequest, AIAnalyzeRequest, AIAnalyzeOut,
    CommentCreate, CommentOut, AttachmentOut, WorklogOut,
    TicketLinkCreate, TicketLinkOut,
)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

os.makedirs(settings.upload_dir, exist_ok=True)

VALID_STATUSES = ["Backlog", "To Do", "In Progress", "In Review", "Done", "Blocked"]

# Allowed forward/back transitions per status.
# None means any transition is allowed from that status.
ALLOWED_TRANSITIONS: Dict[str, Optional[List[str]]] = {
    "Backlog":     ["To Do", "In Progress"],
    "To Do":       ["In Progress", "Backlog"],
    "In Progress": ["In Review", "To Do", "Blocked", "Done"],
    "In Review":   ["In Progress", "Done", "Blocked"],
    "Blocked":     ["In Progress", "To Do"],
    "Done":        ["In Progress", "To Do"],  # allow re-open
}
VALID_ISSUE_TYPES = {"Story", "Bug", "Task", "Epic", "Subtask", "Improvement"}
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp",
    ".mp4", ".webm", ".mov",
    ".pdf", ".txt", ".md", ".csv", ".xlsx", ".xls", ".docx", ".doc",
    ".zip", ".tar", ".gz",
    ".json", ".xml", ".yaml", ".yml",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _next_jira_key(db: Session, org_id: str, pod: Optional[str] = None) -> str:
    import hashlib
    sa = __import__("sqlalchemy")
    prefix = (pod or "TRKLY").strip().upper()
    # Advisory lock scoped per (org, pod prefix) to prevent concurrent duplicate key generation
    lock_key = f"{org_id}:{prefix}"
    lock_id = int(hashlib.md5(lock_key.encode()).hexdigest()[:8], 16) % (2**31)
    db.execute(sa.text(f"SELECT pg_advisory_xact_lock({lock_id})"))
    # Include soft-deleted rows so numbers are never reused (avoids unique constraint conflicts)
    result = db.execute(
        sa.text(
            "SELECT COUNT(*) FROM jira_tickets "
            "WHERE org_id = :oid AND project_key = :prefix"
        ),
        {"oid": org_id, "prefix": prefix},
    ).scalar()
    return f"{prefix}-{(result or 0) + 1}"


def _write_audit(db: Session, entity_id: str, org_id: str, user_id: str, action: str, diff: dict):
    from app.models.base import gen_uuid
    db.add(AuditLog(
        id=gen_uuid(),
        entity_type="ticket",
        entity_id=entity_id,
        user_id=user_id,
        org_id=org_id,
        action=action,
        diff_json=diff,
    ))


def _resolve_ticket(db: Session, org_id: str, ticket_id: str) -> Optional[JiraTicket]:
    """Look up by UUID id first, then fallback to jira_key."""
    try:
        uuid.UUID(ticket_id)
    except ValueError:
        return db.query(JiraTicket).filter(
            JiraTicket.jira_key == ticket_id,
            JiraTicket.org_id == org_id,
            JiraTicket.is_deleted == False,
        ).first()

    return db.query(JiraTicket).filter(
        JiraTicket.id == ticket_id,
        JiraTicket.org_id == org_id,
        JiraTicket.is_deleted == False,
    ).first() or db.query(JiraTicket).filter(
        JiraTicket.jira_key == ticket_id,
        JiraTicket.org_id == org_id,
        JiraTicket.is_deleted == False,
    ).first()


def _attachment_url(filepath: str) -> str:
    filename = os.path.basename(filepath)
    return f"/uploads/{filename}"


def _to_out(t: JiraTicket, db: Session = None) -> dict:
    created = t.jira_created.isoformat() if t.jira_created else (t.synced_at.isoformat() if t.synced_at else None)
    updated = t.jira_updated.isoformat() if t.jira_updated else (t.synced_at.isoformat() if t.synced_at else None)

    parent_key = None
    epic_key = None
    if db is not None:
        if t.parent_id:
            parent = db.query(JiraTicket).filter(JiraTicket.id == t.parent_id).first()
            if parent:
                parent_key = parent.jira_key
        if t.epic_id:
            epic = db.query(JiraTicket).filter(JiraTicket.id == t.epic_id).first()
            if epic:
                epic_key = epic.jira_key

    return {
        "id":             t.id,
        "key":            t.jira_key,
        "org_id":         t.org_id,
        "jira_key":       t.jira_key,
        "project_key":    t.project_key,
        "project_name":   t.project_name,
        "summary":        t.summary,
        "description":    t.description,
        "issue_type":     t.issue_type,
        "priority":       t.priority,
        "status":         t.status,
        "pod":            t.pod,
        "client":         t.client,
        "assignee":       t.assignee,
        "assignee_email": t.assignee_email,
        "reporter":       t.reporter,
        "story_points":   t.story_points,
        "labels":         t.labels or [],
        "sprint_id":      t.sprint_id,
        "due_date":       t.due_date.isoformat() if t.due_date else None,
        "custom_fields":  t.custom_fields,
        "hours_spent":    t.hours_spent or 0,
        "original_estimate_hours": t.original_estimate_hours or 0,
        "remaining_estimate_hours": t.remaining_estimate_hours or 0,
        "url":            t.url,
        "worklogs":       [],
        "is_deleted":     t.is_deleted,
        "created_at":     t.synced_at,
        "created":        created,
        "updated":        updated,
        "fix_version":    t.fix_version,
        "parent_key":     parent_key,
        "epic_key":       epic_key,
    }


async def _embed_ticket_bg(ticket_id: str, title: str, description: str):
    import logging
    try:
        from app.ai.search import embed_and_store_ticket
        db = SessionLocal()
        await embed_and_store_ticket(ticket_id, title, description, db)
        db.close()
    except Exception as e:
        logging.getLogger(__name__).warning(f"Auto-embed failed for {ticket_id}: {e}")


# ── CREATE ────────────────────────────────────────────────────────────────────

@router.post("/nl-create", response_model=dict, status_code=201)
async def nl_create_ticket(
    body: NLCreateRequest,
    background_tasks: BackgroundTasks,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Create a ticket from plain English — NOVA extracts structured fields."""
    from app.ai.ticket_intelligence import full_analysis
    analysis = await full_analysis(body.text, user.org_id)
    fields   = analysis.get("fields", {})

    if "error" in fields:
        fields = {"title": body.text[:100]}

    raw_issue_type = fields.get("issue_type", "Task")
    raw_priority   = fields.get("priority", "Medium")
    raw_sp         = fields.get("story_points")

    from app.models.base import gen_uuid
    # pod from the request body takes priority; AI extraction is a fallback
    pod = body.pod or fields.get("pod")
    jira_key = _next_jira_key(db, user.org_id, pod)
    ticket = JiraTicket(
        id=gen_uuid(),
        org_id=user.org_id,
        jira_key=jira_key,
        project_key=jira_key.split("-")[0],
        summary=fields.get("title", body.text[:100]),
        description=fields.get("description"),
        issue_type=raw_issue_type if raw_issue_type in VALID_ISSUE_TYPES else "Task",
        priority=raw_priority if raw_priority in {"Highest", "High", "Medium", "Low", "Lowest"} else "Medium",
        status="To Do",
        pod=pod,
        client=fields.get("client"),
        assignee=fields.get("assignee"),
        reporter=user.name,
        story_points=int(raw_sp) if isinstance(raw_sp, (int, float)) and int(raw_sp) in {1,2,3,5,8,13,21} else None,
        labels=fields.get("labels") or [],
        is_deleted=False,
    )
    db.add(ticket)
    _write_audit(db, ticket.id, user.org_id, user.id, "nl_created", {"raw": body.text})
    db.commit()
    db.refresh(ticket)

    background_tasks.add_task(_embed_ticket_bg, ticket.id, ticket.summary, ticket.description or "")

    return {
        "ticket":         _to_out(ticket),
        "analysis":       analysis,
        "has_duplicates": analysis.get("has_duplicates", False),
        "duplicates":     analysis.get("duplicates", []),
    }


@router.post("/ai-analyze", response_model=AIAnalyzeOut)
async def ai_analyze(
    body: AIAnalyzeRequest,
    user: User = Depends(get_current_user),
):
    """Analyse plain-English text with NOVA — returns structured fields + duplicate check."""
    from app.ai.ticket_intelligence import full_analysis
    result = await full_analysis(body.text, user.org_id, body.available_users)
    return AIAnalyzeOut(
        fields=result.get("fields", {}),
        duplicates=result.get("duplicates", []),
        has_duplicates=result.get("has_duplicates", False),
        confidence=result.get("confidence"),
    )


@router.get("/{ticket_key}/code-context")
async def get_code_context(
    ticket_key: str,
    title: str = Query(""),
    description: str = Query(""),
    user: User = Depends(get_current_user),
):
    """AI generates search terms, then searches all configured GitHub repos for relevant files and PRs."""
    from app.services.github import search_all_repos, is_configured
    if not is_configured():
        return {"connected": False, "files": [], "prs": []}
    result = await search_all_repos(ticket_key=ticket_key, title=title, description=description)
    return {"connected": True, **result}


@router.post("", response_model=TicketOut, status_code=201)
async def create_ticket(
    body: TicketCreate,
    background_tasks: BackgroundTasks,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.base import gen_uuid
    jira_key = body.jira_key or _next_jira_key(db, user.org_id, body.pod)
    # Resolve parent and epic by key
    parent_id = None
    if body.parent_key:
        parent = db.query(JiraTicket).filter(
            JiraTicket.jira_key == body.parent_key,
            JiraTicket.org_id == user.org_id,
            JiraTicket.is_deleted == False,
        ).first()
        if parent:
            parent_id = parent.id

    epic_id = None
    if body.epic_key:
        epic = db.query(JiraTicket).filter(
            JiraTicket.jira_key == body.epic_key,
            JiraTicket.org_id == user.org_id,
            JiraTicket.is_deleted == False,
        ).first()
        if epic:
            epic_id = epic.id

    ticket = JiraTicket(
        id=gen_uuid(),
        org_id=user.org_id,
        jira_key=jira_key,
        project_key=jira_key.split("-")[0],
        summary=body.summary,
        description=body.description,
        issue_type=body.issue_type or "Task",
        priority=body.priority or "Medium",
        status=body.status or "To Do",
        pod=body.pod,
        client=body.client,
        assignee=body.assignee,
        assignee_email=body.assignee_email,
        reporter=body.reporter or user.name,
        story_points=body.story_points,
        labels=body.labels or [],
        sprint_id=body.sprint_id,
        due_date=body.due_date,
        fix_version=body.fix_version,
        parent_id=parent_id,
        epic_id=epic_id,
        original_estimate_hours=body.original_estimate_hours or 0,
        remaining_estimate_hours=body.remaining_estimate_hours or 0,
        is_deleted=False,
    )
    db.add(ticket)
    _write_audit(db, ticket.id, user.org_id, user.id, "created", {"summary": body.summary})
    db.commit()
    db.refresh(ticket)

    # Automation + webhook hooks
    from app.services.automation_engine import run_automations
    from app.services.webhook_service import dispatch_event
    await run_automations("ticket_created", {"ticket_id": ticket.id, "ticket_key": ticket.jira_key}, user.org_id, ticket.pod or "", db)
    await dispatch_event(user.org_id, "ticket_created", {
        "ticket_key": ticket.jira_key,
        "summary": ticket.summary,
        "assignee": ticket.assignee,
        "user": user.name,
        "link": f"/tickets?key={ticket.jira_key}",
    }, db)

    background_tasks.add_task(_embed_ticket_bg, ticket.id, ticket.summary, ticket.description or "")
    return TicketOut(**_to_out(ticket, db))


# ── LIST ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_tickets(
    pod:        Optional[str] = Query(None),
    status:     Optional[str] = Query(None),
    assignee:   Optional[str] = Query(None),
    user_filter: Optional[str] = Query(None, alias="user"),
    client:     Optional[str] = Query(None),
    issue_type: Optional[str] = Query(None),
    search:     Optional[str] = Query(None),
    limit:      int           = Query(50, le=200),
    offset:     int           = Query(0),
    db:      Session         = Depends(get_db),
    user:    User            = Depends(get_current_user),
    scope:   VisibilityScope = Depends(get_visibility_scope),
):
    from sqlalchemy import or_

    effective_assignee = assignee or user_filter
    q = db.query(JiraTicket).filter(
        JiraTicket.org_id == user.org_id,
        JiraTicket.is_deleted == False,
    )

    # Apply role-based visibility via VisibilityScope
    if not scope.unrestricted:
        conditions = []
        if scope.allowed_pods:
            conditions.append(JiraTicket.pod.in_(scope.allowed_pods))
        if scope.allowed_emails:
            conditions.append(JiraTicket.assignee_email.in_(scope.allowed_emails))
        if conditions:
            q = q.filter(or_(*conditions))

    if pod:                q = q.filter(JiraTicket.pod == pod)
    if status:             q = q.filter(JiraTicket.status == status)
    if effective_assignee: q = q.filter(JiraTicket.assignee.ilike(f"%{effective_assignee}%"))
    if client:             q = q.filter(JiraTicket.client == client)
    if issue_type:         q = q.filter(JiraTicket.issue_type == issue_type)
    if search:             q = q.filter(JiraTicket.summary.ilike(f"%{search}%"))

    total   = q.count()
    tickets = q.order_by(JiraTicket.synced_at.desc()).offset(offset).limit(limit).all()
    return {
        "tickets": [_to_out(t) for t in tickets],
        "total":   total,
        "limit":   limit,
        "offset":  offset,
    }


# ── GET / UPDATE / DELETE ─────────────────────────────────────────────────────

@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(
    ticket_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return TicketOut(**_to_out(ticket, db))


@router.put("/{ticket_id}", response_model=TicketOut)
async def update_ticket(
    ticket_id: str,
    body: TicketUpdate,
    background_tasks: BackgroundTasks,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    update_data = body.model_dump(exclude_none=True)

    # Handle hierarchy key→id resolution outside the generic loop
    if "parent_key" in update_data:
        pk = update_data.pop("parent_key")
        parent = db.query(JiraTicket).filter(
            JiraTicket.jira_key == pk,
            JiraTicket.org_id == user.org_id,
            JiraTicket.is_deleted == False,
        ).first() if pk else None
        new_parent_id = parent.id if parent else None
        if ticket.parent_id != new_parent_id:
            update_data["parent_id"] = new_parent_id

    if "epic_key" in update_data:
        ek = update_data.pop("epic_key")
        epic = db.query(JiraTicket).filter(
            JiraTicket.jira_key == ek,
            JiraTicket.org_id == user.org_id,
            JiraTicket.is_deleted == False,
        ).first() if ek else None
        new_epic_id = epic.id if epic else None
        if ticket.epic_id != new_epic_id:
            update_data["epic_id"] = new_epic_id

    diff = {}
    for field, value in update_data.items():
        old_val = getattr(ticket, field, None)
        # For date fields, compare as strings to avoid type mismatch
        old_cmp = old_val.isoformat() if hasattr(old_val, "isoformat") else old_val
        new_cmp = value.isoformat() if hasattr(value, "isoformat") else value
        # For JSONB custom_fields, merge instead of replace
        if field == "custom_fields" and old_val and new_cmp:
            merged = {**old_val, **new_cmp}
            if merged != old_val:
                diff[field] = {"old": old_val, "new": merged}
                ticket.custom_fields = merged
            continue
        if old_cmp != new_cmp:
            diff[field] = {"old": old_cmp, "new": new_cmp}
            setattr(ticket, field, value)

    if diff:
        _write_audit(db, ticket.id, user.org_id, user.id, "updated", diff)

        if "assignee" in diff and diff["assignee"]["new"]:
            from app.models.notification import Notification as Notif
            from app.models.base import gen_uuid as _gen
            assigned_user = db.query(User).filter(
                User.org_id == user.org_id,
                User.name == diff["assignee"]["new"],
            ).first()
            if assigned_user and assigned_user.id != user.id:
                db.add(Notif(
                    id=_gen(), org_id=user.org_id, user_id=assigned_user.id,
                    type="ticket_assigned",
                    title=f"Assigned to you: {ticket.jira_key}",
                    body=ticket.summary[:200],
                    link=f"/tickets?key={ticket.jira_key}",
                ))

        db.commit()
        db.refresh(ticket)
        background_tasks.add_task(_embed_ticket_bg, ticket.id, ticket.summary, ticket.description or "")
    return TicketOut(**_to_out(ticket, db))


@router.delete("/{ticket_id}", status_code=204)
async def delete_ticket(
    ticket_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    ticket.is_deleted = True
    _write_audit(db, ticket.id, user.org_id, user.id, "deleted", {})
    db.commit()


@router.post("/{ticket_id}/status", response_model=TicketOut)
async def transition_status(
    ticket_id: str,
    body: StatusTransition,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {VALID_STATUSES}")

    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    old_status = ticket.status
    allowed = ALLOWED_TRANSITIONS.get(old_status)
    if allowed is not None and body.status not in allowed:
        raise HTTPException(
            422,
            f"Transition from '{old_status}' to '{body.status}' is not allowed. "
            f"Allowed: {allowed}",
        )

    ticket.status = body.status
    _write_audit(db, ticket.id, user.org_id, user.id, "status_changed", {
        "old": old_status, "new": body.status
    })

    if body.status == "Blocked" and ticket.assignee:
        from app.models.notification import Notification as Notif
        from app.models.base import gen_uuid as _gen
        assignee_user = db.query(User).filter(
            User.org_id == user.org_id,
            User.name == ticket.assignee,
        ).first()
        if assignee_user:
            db.add(Notif(
                id=_gen(), org_id=user.org_id, user_id=assignee_user.id,
                type="blocked_ticket",
                title=f"{ticket.jira_key} has been blocked",
                body=ticket.summary[:200],
                link=f"/tickets?key={ticket.jira_key}",
            ))

    db.commit()
    db.refresh(ticket)
    from app.services.automation_engine import run_automations
    from app.services.webhook_service import dispatch_event
    import logging as _logging
    _log = _logging.getLogger(__name__)
    await run_automations("status_change", {"ticket_id": ticket.id, "ticket_key": ticket.jira_key, "old_status": old_status, "new_status": body.status}, user.org_id, ticket.pod or "", db)
    try:
        sent = await dispatch_event(user.org_id, "status_changed", {
            "ticket_key": ticket.jira_key,
            "summary": ticket.summary,
            "old_status": old_status,
            "new_status": body.status,
            "user": user.name,
            "link": f"/tickets?key={ticket.jira_key}",
        }, db)
        _log.info(f"[webhook] status_changed dispatched to {sent} integration(s) for {ticket.jira_key}")
    except Exception as _e:
        _log.error(f"[webhook] dispatch_event failed for status_changed: {_e}")
    return TicketOut(**_to_out(ticket, db))


# ── COMMENTS ─────────────────────────────────────────────────────────────────

@router.get("/{ticket_id}/comments", response_model=List[CommentOut])
async def list_comments(
    ticket_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    comments = db.query(TicketComment).filter(
        TicketComment.ticket_id == ticket.id,
        TicketComment.is_deleted == False,
    ).order_by(TicketComment.created_at).all()

    result = []
    for c in comments:
        author_name = None
        if c.author_id:
            au = db.query(User).filter(User.id == c.author_id).first()
            author_name = au.name if au else None
        result.append(CommentOut(
            id=c.id, ticket_id=c.ticket_id, author_id=c.author_id,
            body=c.body, parent_id=c.parent_id,
            created_at=c.created_at, updated_at=c.updated_at,
            is_deleted=c.is_deleted, author_name=author_name,
        ))
    return result


@router.post("/{ticket_id}/comments", response_model=CommentOut, status_code=201)
async def add_comment(
    ticket_id: str,
    body: CommentCreate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    from app.models.base import gen_uuid
    comment = TicketComment(
        id=gen_uuid(),
        ticket_id=ticket.id,
        author_id=user.id,
        body=body.body,
        parent_id=body.parent_id,
    )
    db.add(comment)
    _write_audit(db, ticket.id, user.org_id, user.id, "commented", {"body": body.body[:100]})

    from app.models.notification import Notification as Notif
    from app.models.base import gen_uuid as _gen
    import re as _re

    notified_ids: set = set()

    # Notify ticket assignee on new comment (skip if commenter is the assignee)
    if ticket.assignee:
        assignee_user = db.query(User).filter(
            User.org_id == user.org_id,
            User.name == ticket.assignee,
        ).first()
        if assignee_user and assignee_user.id != user.id:
            db.add(Notif(
                id=_gen(), org_id=user.org_id, user_id=assignee_user.id,
                type="ticket_commented",
                title=f"{user.name} commented on {ticket.jira_key}",
                body=body.body[:200],
                link=f"/tickets?key={ticket.jira_key}",
            ))
            notified_ids.add(assignee_user.id)

    # Parse @mentions and notify each mentioned user
    mentioned_names = _re.findall(r"@([\w.]+(?:\s[\w.]+)?)", body.body)
    for raw_name in mentioned_names:
        # Match by name (case-insensitive, spaces or dots as separator)
        name_normalized = raw_name.replace(".", " ").strip()
        mentioned_user = db.query(User).filter(
            User.org_id == user.org_id,
        ).all()
        matched = next(
            (u for u in mentioned_user
             if u.name.lower() == name_normalized.lower()
             or u.name.lower().replace(" ", ".") == raw_name.lower()),
            None,
        )
        if matched and matched.id != user.id and matched.id not in notified_ids:
            db.add(Notif(
                id=_gen(), org_id=user.org_id, user_id=matched.id,
                type="mentioned",
                title=f"{user.name} mentioned you in {ticket.jira_key}",
                body=body.body[:200],
                link=f"/tickets?key={ticket.jira_key}",
            ))
            notified_ids.add(matched.id)

    db.commit()
    db.refresh(comment)
    return CommentOut(
        id=comment.id, ticket_id=comment.ticket_id, author_id=comment.author_id,
        body=comment.body, parent_id=comment.parent_id,
        created_at=comment.created_at, updated_at=comment.updated_at,
        is_deleted=comment.is_deleted, author_name=user.name,
    )


@router.put("/{ticket_id}/comments/{comment_id}", response_model=CommentOut)
async def edit_comment(
    ticket_id:  str,
    comment_id: str,
    body: CommentCreate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    comment = db.query(TicketComment).filter(
        TicketComment.id == comment_id,
        TicketComment.ticket_id == ticket.id,
        TicketComment.is_deleted == False,
    ).first()
    if not comment:
        raise HTTPException(404, "Comment not found")
    if comment.author_id != user.id and (user.role or "") != "admin":
        raise HTTPException(403, "Not allowed to edit this comment")
    comment.body = body.body
    db.commit()
    db.refresh(comment)
    return CommentOut(
        id=comment.id, ticket_id=comment.ticket_id, author_id=comment.author_id,
        body=comment.body, parent_id=comment.parent_id,
        created_at=comment.created_at, updated_at=comment.updated_at,
        is_deleted=comment.is_deleted, author_name=user.name,
    )


@router.delete("/{ticket_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    ticket_id:  str,
    comment_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    # Resolve ticket by jira_key or UUID to get the actual UUID primary key
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    comment = db.query(TicketComment).filter(
        TicketComment.id == comment_id,
        TicketComment.ticket_id == ticket.id,
        TicketComment.is_deleted == False,
    ).first()
    if not comment:
        raise HTTPException(404, "Comment not found")
    if comment.author_id != user.id and (user.role or "") != "admin":
        raise HTTPException(403, "Not allowed to delete this comment")
    comment.is_deleted = True
    _write_audit(db, ticket.id, user.org_id, user.id, "deleted comment", {})
    db.commit()


# ── ATTACHMENTS ───────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    ticket_id: str,
    file: UploadFile = File(...),
    db:   Session    = Depends(get_db),
    user: User       = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
        raise HTTPException(415, f"File type '{ext}' not allowed")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest      = os.path.join(settings.upload_dir, safe_name)

    # Read in chunks with size guard
    CHUNK = 256 * 1024  # 256 KB
    contents = bytearray()
    while True:
        chunk = await file.read(CHUNK)
        if not chunk:
            break
        contents.extend(chunk)
        if len(contents) > settings.max_upload_bytes:
            raise HTTPException(413, "File too large")

    with open(dest, "wb") as f:
        f.write(contents)

    from app.models.base import gen_uuid
    attachment = TicketAttachment(
        id=gen_uuid(),
        ticket_id=ticket.id,
        filename=file.filename or safe_name,
        filepath=dest,
        size_bytes=len(contents),
        uploaded_by=user.id,
    )
    db.add(attachment)
    _write_audit(db, ticket.id, user.org_id, user.id, "attached file", {"filename": file.filename})
    db.commit()
    db.refresh(attachment)

    out = AttachmentOut.model_validate(attachment)
    out.url = _attachment_url(attachment.filepath)
    return out


@router.get("/{ticket_id}/attachments", response_model=List[AttachmentOut])
async def list_attachments(
    ticket_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    attachments = db.query(TicketAttachment).filter(
        TicketAttachment.ticket_id == ticket.id
    ).order_by(TicketAttachment.created_at).all()

    result = []
    for a in attachments:
        out = AttachmentOut.model_validate(a)
        out.url = _attachment_url(a.filepath)
        result.append(out)
    return result


# ── WORKLOGS ─────────────────────────────────────────────────────────────────

@router.get("/{ticket_id}/worklogs", response_model=List[dict])
async def list_worklogs(
    ticket_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.ticket import Worklog
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    worklogs = db.query(Worklog).filter(
        Worklog.ticket_id == ticket.id
    ).order_by(Worklog.log_date.desc()).all()

    return [
        {
            "id":           wl.id,
            "author":       wl.author,
            "author_email": wl.author_email,
            "log_date":     wl.log_date.isoformat() if wl.log_date else None,
            "hours":        wl.hours,
            "comment":      wl.comment,
        }
        for wl in worklogs
    ]


@router.post("/{ticket_id}/worklogs", status_code=201)
async def log_time(
    ticket_id: str,
    body: dict,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.base import gen_uuid
    from app.models.ticket import Worklog
    import datetime

    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    hours    = float(body.get("hours") or 0)
    if hours <= 0:
        raise HTTPException(400, "hours must be greater than 0")
    comment  = body.get("comment") or body.get("note") or ""
    log_date_str = body.get("date")
    log_date = None
    if log_date_str:
        try:
            log_date = datetime.date.fromisoformat(log_date_str)
        except ValueError:
            log_date = datetime.date.today()
    else:
        log_date = datetime.date.today()

    worklog = Worklog(
        id=gen_uuid(),
        ticket_id=ticket.id,
        author=user.name,
        author_email=user.email,
        log_date=log_date,
        hours=hours,
        comment=comment,
    )
    db.add(worklog)
    ticket.hours_spent = (ticket.hours_spent or 0) + hours
    _write_audit(db, ticket.id, user.org_id, user.id, "logged time", {
        "hours": hours, "date": log_date_str, "comment": comment
    })

    from app.models.notification import Notification as Notif
    db.add(Notif(
        id=gen_uuid(), org_id=user.org_id, user_id=user.id,
        type="time_logged",
        title=f"{hours}h logged on {ticket.jira_key}",
        body=comment or ticket.summary[:200],
        link=f"/tickets?key={ticket.jira_key}",
    ))

    db.commit()
    db.refresh(worklog)

    return {
        "id":       worklog.id,
        "ticket_id": worklog.ticket_id,
        "hours":    worklog.hours,
        "comment":  worklog.comment,
        "log_date": worklog.log_date.isoformat() if worklog.log_date else None,
        "author":   worklog.author,
    }


# ── TICKET LINKS ──────────────────────────────────────────────────────────────

@router.get("/{ticket_id}/links", response_model=List[TicketLinkOut])
async def list_links(
    ticket_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    links = db.query(TicketLink).filter(
        TicketLink.source_ticket_id == ticket.id
    ).order_by(TicketLink.created_at).all()

    return [
        TicketLinkOut(
            id=lnk.id,
            source_ticket_id=lnk.source_ticket_id,
            target_key=lnk.target_key,
            target_summary=lnk.target_summary,
            link_type=lnk.link_type,
            created_at=lnk.created_at,
        )
        for lnk in links
    ]


@router.post("/{ticket_id}/links", response_model=TicketLinkOut, status_code=201)
async def add_link(
    ticket_id: str,
    body: TicketLinkCreate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.base import gen_uuid

    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    # Try to fetch the target ticket's summary for display
    target_key = body.target_key.strip().upper()
    target = db.query(JiraTicket).filter(
        JiraTicket.jira_key == target_key,
        JiraTicket.org_id == user.org_id,
        JiraTicket.is_deleted == False,
    ).first()

    link = TicketLink(
        id=gen_uuid(),
        org_id=user.org_id,
        source_ticket_id=ticket.id,
        target_key=target_key,
        target_summary=target.summary if target else None,
        link_type=body.link_type,
    )
    db.add(link)
    _write_audit(db, ticket.id, user.org_id, user.id, "linked", {
        "link_type": body.link_type, "target": target_key
    })
    db.commit()
    db.refresh(link)

    return TicketLinkOut(
        id=link.id,
        source_ticket_id=link.source_ticket_id,
        target_key=link.target_key,
        target_summary=link.target_summary,
        link_type=link.link_type,
        created_at=link.created_at,
    )


@router.delete("/{ticket_id}/links/{link_id}", status_code=204)
async def remove_link(
    ticket_id: str,
    link_id:   str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    link = db.query(TicketLink).filter(
        TicketLink.id == link_id,
        TicketLink.source_ticket_id == ticket.id,
    ).first()
    if not link:
        raise HTTPException(404, "Link not found")
    db.delete(link)
    db.commit()


# ── EPIC LINK ─────────────────────────────────────────────────────────────────

class EpicLinkPayload(BaseModel):
    epic_id: Optional[str] = None


@router.post("/{ticket_id}/epic", response_model=TicketOut)
async def link_ticket_to_epic(
    ticket_id: str,
    body: EpicLinkPayload,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    ticket.epic_id = body.epic_id
    _write_audit(db, ticket.id, user.org_id, user.id, "epic_linked", {"epic_id": body.epic_id})
    db.commit()
    db.refresh(ticket)
    return TicketOut(**_to_out(ticket, db))


# ── SUB-TASKS ─────────────────────────────────────────────────────────────────

class SubtaskCreate(BaseModel):
    summary: str
    assignee: Optional[str] = None
    story_points: Optional[int] = None


@router.get("/{ticket_id}/subtasks", response_model=List[TicketOut])
async def list_subtasks(
    ticket_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    children = db.query(JiraTicket).filter(
        JiraTicket.parent_id == ticket.id,
        JiraTicket.org_id == user.org_id,
        JiraTicket.is_deleted == False,
    ).all()
    return [TicketOut(**_to_out(t)) for t in children]


@router.post("/{ticket_id}/subtasks", response_model=TicketOut, status_code=201)
async def create_subtask(
    ticket_id: str,
    body: SubtaskCreate,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    parent = _resolve_ticket(db, user.org_id, ticket_id)
    if not parent:
        raise HTTPException(404, "Ticket not found")

    from app.models.base import gen_uuid
    sub = JiraTicket(
        id=gen_uuid(),
        org_id=user.org_id,
        jira_key=_next_jira_key(db, user.org_id),
        project_key=parent.project_key,
        summary=body.summary,
        issue_type="Subtask",
        priority=parent.priority,
        status="To Do",
        pod=parent.pod,
        client=parent.client,
        assignee=body.assignee,
        reporter=user.name,
        story_points=body.story_points,
        parent_id=parent.id,
        is_deleted=False,
    )
    db.add(sub)
    _write_audit(db, parent.id, user.org_id, user.id, "subtask_created", {"child_key": sub.jira_key, "summary": body.summary})
    db.commit()
    db.refresh(sub)
    return TicketOut(**_to_out(sub))


@router.delete("/{ticket_id}/subtasks/{child_key}", status_code=204)
async def unlink_subtask(
    ticket_id: str,
    child_key: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    parent = _resolve_ticket(db, user.org_id, ticket_id)
    if not parent:
        raise HTTPException(404, "Ticket not found")

    child = db.query(JiraTicket).filter(
        JiraTicket.jira_key == child_key,
        JiraTicket.org_id == user.org_id,
        JiraTicket.parent_id == parent.id,
        JiraTicket.is_deleted == False,
    ).first()
    if not child:
        raise HTTPException(404, "Sub-task not found")

    child.parent_id = None
    _write_audit(db, parent.id, user.org_id, user.id, "subtask_unlinked", {"child_key": child_key})
    db.commit()


# ── ACTIVITY LOG ──────────────────────────────────────────────────────────────

@router.get("/{ticket_id}/activity", response_model=List[dict])
async def ticket_activity(
    ticket_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    ticket = _resolve_ticket(db, user.org_id, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    logs = db.query(AuditLog).filter(
        AuditLog.entity_type == "ticket",
        AuditLog.entity_id   == ticket.id,
    ).order_by(AuditLog.created_at.desc()).limit(50).all()

    result = []
    for log in logs:
        actor_name = None
        if log.user_id:
            u = db.query(User).filter(User.id == log.user_id).first()
            actor_name = u.name if u else None
        result.append({
            "id":         log.id,
            "action":     log.action,
            "diff":       log.diff_json,
            "actor":      actor_name,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })
    return result
