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
  GET    /api/tickets/:id/activity       Audit log for ticket
"""

import os
import uuid
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File, Query
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.core.dependencies import get_current_user
from app.core.config import settings
from app.models.ticket import JiraTicket, TicketComment, TicketAttachment
from app.models.audit import AuditLog
from app.models.user import User
from app.schemas.ticket import (
    TicketCreate, TicketUpdate, TicketOut, StatusTransition,
    NLCreateRequest, AIAnalyzeRequest, AIAnalyzeOut,
    CommentCreate, CommentOut, AttachmentOut,
)

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

os.makedirs(settings.upload_dir, exist_ok=True)

VALID_STATUSES = ["Backlog", "To Do", "In Progress", "In Review", "Done", "Blocked"]


# ── helpers ───────────────────────────────────────────────────────────────────

def _next_jira_key(db: Session, org_id: str) -> str:
    result = db.execute(
        __import__("sqlalchemy").text("SELECT COUNT(*) FROM jira_tickets WHERE org_id = :oid"),
        {"oid": org_id},
    ).scalar()
    return f"TRKLY-{(result or 0) + 1}"


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
    # Only query by id if ticket_id looks like a UUID; otherwise PG throws a DataError
    # trying to cast a jira key (e.g. 'SNOP-147') to the UUID column type.
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


def _to_out(t: JiraTicket) -> dict:
    created = t.jira_created.isoformat() if t.jira_created else (t.synced_at.isoformat() if t.synced_at else None)
    updated = t.jira_updated.isoformat() if t.jira_updated else (t.synced_at.isoformat() if t.synced_at else None)
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
        "story_points":   t.story_points,
        "labels":         t.labels or [],
        "sprint_id":      t.sprint_id,
        "due_date":       t.due_date.isoformat() if t.due_date else None,
        "hours_spent":    t.hours_spent or 0,
        "original_estimate_hours": t.original_estimate_hours or 0,
        "remaining_estimate_hours": t.remaining_estimate_hours or 0,
        "url":            t.url,
        "worklogs":       [],
        "is_deleted":     t.is_deleted,
        "created_at":     t.synced_at,
        "created":        created,
        "updated":        updated,
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

    # If NOVA is offline, fall back to raw text as title rather than rejecting
    if "error" in fields:
        fields = {"title": body.text[:100]}

    from app.models.base import gen_uuid
    jira_key = _next_jira_key(db, user.org_id)
    ticket = JiraTicket(
        id=gen_uuid(),
        org_id=user.org_id,
        jira_key=jira_key,
        project_key=jira_key.split("-")[0],
        summary=fields.get("title", body.text[:100]),
        description=fields.get("description"),
        issue_type=fields.get("issue_type", "Task"),
        priority=fields.get("priority", "Medium"),
        status="To Do",
        pod=fields.get("pod"),
        client=fields.get("client"),
        assignee=fields.get("assignee"),
        story_points=fields.get("story_points"),
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
    result = await full_analysis(body.text, user.org_id)
    return AIAnalyzeOut(
        fields=result.get("fields", {}),
        duplicates=result.get("duplicates", []),
        has_duplicates=result.get("has_duplicates", False),
        confidence=result.get("confidence"),
    )


@router.post("", response_model=TicketOut, status_code=201)
async def create_ticket(
    body: TicketCreate,
    background_tasks: BackgroundTasks,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    from app.models.base import gen_uuid
    jira_key = body.jira_key or _next_jira_key(db, user.org_id)
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
        story_points=body.story_points,
        labels=body.labels or [],
        sprint_id=body.sprint_id,
        due_date=body.due_date,
        is_deleted=False,
    )
    db.add(ticket)
    _write_audit(db, ticket.id, user.org_id, user.id, "created", {"summary": body.summary})
    db.commit()
    db.refresh(ticket)

    background_tasks.add_task(_embed_ticket_bg, ticket.id, ticket.summary, ticket.description or "")
    return TicketOut(**_to_out(ticket))


# ── LIST ──────────────────────────────────────────────────────────────────────

@router.get("", response_model=dict)
async def list_tickets(
    pod:        Optional[str] = Query(None),
    status:     Optional[str] = Query(None),
    assignee:   Optional[str] = Query(None),
    client:     Optional[str] = Query(None),
    issue_type: Optional[str] = Query(None),
    search:     Optional[str] = Query(None),
    limit:      int           = Query(50, le=200),
    offset:     int           = Query(0),
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    q = db.query(JiraTicket).filter(
        JiraTicket.org_id == user.org_id,
        JiraTicket.is_deleted == False,
    )
    if pod:        q = q.filter(JiraTicket.pod == pod)
    if status:     q = q.filter(JiraTicket.status == status)
    if assignee:   q = q.filter(JiraTicket.assignee.ilike(f"%{assignee}%"))
    if client:     q = q.filter(JiraTicket.client == client)
    if issue_type: q = q.filter(JiraTicket.issue_type == issue_type)
    if search:     q = q.filter(JiraTicket.summary.ilike(f"%{search}%"))

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
    return TicketOut(**_to_out(ticket))


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

    diff = {}
    for field, value in body.model_dump(exclude_none=True).items():
        if getattr(ticket, field, None) != value:
            diff[field] = {"old": getattr(ticket, field, None), "new": value}
            setattr(ticket, field, value)

    if diff:
        _write_audit(db, ticket.id, user.org_id, user.id, "updated", diff)
        db.commit()
        db.refresh(ticket)
        background_tasks.add_task(_embed_ticket_bg, ticket.id, ticket.summary, ticket.description or "")
    return TicketOut(**_to_out(ticket))


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

    old_status    = ticket.status
    ticket.status = body.status
    _write_audit(db, ticket.id, user.org_id, user.id, "status_changed", {
        "old": old_status, "new": body.status
    })
    db.commit()
    db.refresh(ticket)
    return TicketOut(**_to_out(ticket))


@router.post("/{key}/status", response_model=TicketOut)
async def transition_status_by_key(
    key: str,
    body: StatusTransition,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    if body.status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {VALID_STATUSES}")

    ticket = db.query(JiraTicket).filter(
        JiraTicket.jira_key == key,
        JiraTicket.org_id == user.org_id,
        JiraTicket.is_deleted == False,
    ).first()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    old_status    = ticket.status
    ticket.status = body.status
    _write_audit(db, ticket.id, user.org_id, user.id, "status_changed", {
        "old": old_status, "new": body.status
    })
    db.commit()
    db.refresh(ticket)
    return TicketOut(**_to_out(ticket))


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
    comment = db.query(TicketComment).filter(
        TicketComment.id == comment_id,
        TicketComment.ticket_id == ticket_id,
        TicketComment.is_deleted == False,
    ).first()
    if not comment:
        raise HTTPException(404, "Comment not found")
    if comment.author_id != user.id and user.role != "admin":
        raise HTTPException(403, "Not allowed to delete this comment")
    comment.is_deleted = True
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

    ext       = os.path.splitext(file.filename or "")[1]
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest      = os.path.join(settings.upload_dir, safe_name)
    contents  = await file.read()

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
    db.commit()
    db.refresh(attachment)
    return AttachmentOut.model_validate(attachment)


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
    return [AttachmentOut.model_validate(a) for a in attachments]


# ── WORKLOGS ─────────────────────────────────────────────────────────────────

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

    hours    = float(body.get("hours", 0))
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

    # Update cached hours_spent on ticket
    ticket.hours_spent = (ticket.hours_spent or 0) + hours
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
