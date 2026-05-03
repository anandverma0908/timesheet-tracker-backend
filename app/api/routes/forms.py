"""
app/api/routes/forms.py — Form templates & public submissions.

Endpoints:
  GET    /api/forms                List templates (auth)
  POST   /api/forms                Create template (auth)
  GET    /api/forms/{id}           Get template (auth)
  POST   /api/forms/{id}/submissions  Public submission (no auth)
  GET    /api/forms/{id}/submissions  List submissions (auth)
  POST   /api/forms/submissions/{id}/convert  Convert submission to ticket (auth)
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.form import FormTemplate, FormSubmission
from app.models.ticket import JiraTicket
from app.models.user import User

router = APIRouter(prefix="/api/forms", tags=["forms"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class FormField(BaseModel):
    name: str
    type: str  # text, number, select, checkbox, textarea
    label: str
    required: bool = False
    options: Optional[List[str]] = None


class FormTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    fields: List[FormField] = Field(default_factory=list)
    is_active: bool = True


class FormTemplateOut(BaseModel):
    id: str
    org_id: str
    name: str
    description: Optional[str]
    fields: List[FormField]
    is_active: bool
    created_at: Optional[str]


class FormSubmissionCreate(BaseModel):
    submitter_email: str
    responses: dict


class FormSubmissionOut(BaseModel):
    id: str
    form_id: str
    org_id: str
    submitter_email: str
    responses: dict
    status: str
    ticket_id: Optional[str]
    created_at: Optional[str]


class ConvertSubmissionRequest(BaseModel):
    title: str
    description: Optional[str] = None
    pod: Optional[str] = None
    client: Optional[str] = None
    issue_type: Optional[str] = "Task"
    priority: Optional[str] = "Medium"
    assignee: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tpl_out(tpl: FormTemplate) -> FormTemplateOut:
    fields = tpl.fields_json or []
    return FormTemplateOut(
        id=str(tpl.id),
        org_id=str(tpl.org_id),
        name=tpl.name,
        description=tpl.description,
        fields=[FormField(**f) for f in fields],
        is_active=tpl.is_active,
        created_at=tpl.created_at.isoformat() if tpl.created_at else None,
    )


def _sub_out(sub: FormSubmission) -> FormSubmissionOut:
    return FormSubmissionOut(
        id=str(sub.id),
        form_id=str(sub.form_id),
        org_id=str(sub.org_id),
        submitter_email=sub.submitter_email,
        responses=sub.responses_json or {},
        status=sub.status,
        ticket_id=sub.ticket_id,
        created_at=sub.created_at.isoformat() if sub.created_at else None,
    )


def _next_jira_key(db: Session, org_id: str, pod: Optional[str] = None) -> str:
    import hashlib
    from sqlalchemy import text
    prefix = (pod or "TRKLY").strip().upper()
    lock_key = f"{org_id}:{prefix}"
    lock_id = int(hashlib.md5(lock_key.encode()).hexdigest()[:8], 16) % (2**31)
    db.execute(text(f"SELECT pg_advisory_xact_lock({lock_id})"))
    result = db.execute(
        text(
            """
            SELECT COUNT(*) FROM jira_tickets
            WHERE org_id = :org_id AND jira_key LIKE :pattern
            """
        ),
        {"org_id": org_id, "pattern": f"{prefix}-%%"},
    ).scalar()
    count = int(result or 0)
    return f"{prefix}-{count + 1}"


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[FormTemplateOut])
async def list_templates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = db.query(FormTemplate).filter(
        FormTemplate.org_id == user.org_id,
        FormTemplate.is_active == True,
    ).order_by(FormTemplate.created_at.desc()).all()
    return [_tpl_out(r) for r in rows]


@router.post("", response_model=FormTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: FormTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = FormTemplate(
        org_id=user.org_id,
        name=payload.name,
        description=payload.description,
        fields_json=[f.model_dump() for f in payload.fields],
        is_active=payload.is_active,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return _tpl_out(tpl)


@router.get("/{id}", response_model=FormTemplateOut)
async def get_template(
    id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = db.query(FormTemplate).filter(
        FormTemplate.id == id,
        FormTemplate.org_id == user.org_id,
    ).first()
    if not tpl:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    return _tpl_out(tpl)


# ── Submissions ───────────────────────────────────────────────────────────────

@router.post("/{id}/submissions", response_model=FormSubmissionOut, status_code=status.HTTP_201_CREATED)
async def create_submission(
    id: str,
    payload: FormSubmissionCreate,
    db: Session = Depends(get_db),
):
    tpl = db.query(FormTemplate).filter(
        FormTemplate.id == id,
        FormTemplate.is_active == True,
    ).first()
    if not tpl:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found or inactive")

    sub = FormSubmission(
        form_id=tpl.id,
        org_id=tpl.org_id,
        submitter_email=payload.submitter_email,
        responses_json=payload.responses,
        status="new",
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return _sub_out(sub)


@router.get("/{id}/submissions", response_model=List[FormSubmissionOut])
async def list_submissions(
    id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    tpl = db.query(FormTemplate).filter(
        FormTemplate.id == id,
        FormTemplate.org_id == user.org_id,
    ).first()
    if not tpl:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")

    rows = db.query(FormSubmission).filter(
        FormSubmission.form_id == id,
        FormSubmission.org_id == user.org_id,
    ).order_by(FormSubmission.created_at.desc()).all()
    return [_sub_out(r) for r in rows]


@router.post("/submissions/{sub_id}/convert", response_model=FormSubmissionOut)
async def convert_submission(
    sub_id: str,
    payload: ConvertSubmissionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sub = db.query(FormSubmission).filter(
        FormSubmission.id == sub_id,
        FormSubmission.org_id == user.org_id,
    ).first()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")

    if sub.ticket_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Already converted")

    key = _next_jira_key(db, str(user.org_id), payload.pod)

    ticket = JiraTicket(
        org_id=user.org_id,
        jira_key=key,
        project_key=payload.pod or "TRKLY",
        project_name=payload.pod or "TRKLY",
        summary=payload.title,
        description=payload.description or "",
        assignee=payload.assignee or user.name,
        assignee_email=payload.assignee or user.email,
        reporter=sub.submitter_email,
        status="To Do",
        client=payload.client or "",
        pod=payload.pod or "",
        issue_type=payload.issue_type or "Task",
        priority=payload.priority or "Medium",
    )
    db.add(ticket)
    db.flush()

    sub.status = "converted"
    sub.ticket_id = key
    db.commit()
    db.refresh(sub)
    return _sub_out(sub)
