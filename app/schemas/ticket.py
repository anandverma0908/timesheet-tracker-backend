from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime, date


class TicketCreate(BaseModel):
    summary:        str
    description:    Optional[str] = None
    issue_type:     Optional[str] = "Task"
    priority:       Optional[str] = "Medium"
    status:         Optional[str] = "To Do"
    pod:            Optional[str] = None
    client:         Optional[str] = None
    assignee:       Optional[str] = None
    assignee_email: Optional[str] = None
    reporter:       Optional[str] = None
    story_points:   Optional[int] = None
    labels:         Optional[List[str]] = None
    sprint_id:      Optional[str] = None
    jira_key:       Optional[str] = None
    due_date:       Optional[date] = None
    parent_key:     Optional[str] = None
    epic_key:       Optional[str] = None
    fix_version:    Optional[str] = None

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_due_date(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v))
        except (ValueError, TypeError):
            return None


class TicketUpdate(BaseModel):
    summary:        Optional[str] = None
    description:    Optional[str] = None
    issue_type:     Optional[str] = None
    priority:       Optional[str] = None
    status:         Optional[str] = None
    pod:            Optional[str] = None
    client:         Optional[str] = None
    assignee:       Optional[str] = None
    assignee_email: Optional[str] = None
    reporter:       Optional[str] = None
    story_points:   Optional[int] = None
    labels:         Optional[List[str]] = None
    sprint_id:      Optional[str] = None
    due_date:       Optional[date] = None
    custom_fields:  Optional[dict] = None
    parent_key:     Optional[str] = None
    epic_key:       Optional[str] = None
    fix_version:    Optional[str] = None

    @field_validator("due_date", mode="before")
    @classmethod
    def parse_due_date(cls, v):
        if v is None or v == "":
            return None
        if isinstance(v, date):
            return v
        try:
            return date.fromisoformat(str(v))
        except (ValueError, TypeError):
            return None


class TicketOut(BaseModel):
    id:             str
    org_id:         str
    jira_key:       str
    summary:        str
    description:    Optional[str] = None
    issue_type:     Optional[str] = None
    priority:       Optional[str] = None
    status:         Optional[str] = None
    pod:            Optional[str] = None
    client:         Optional[str] = None
    assignee:       Optional[str] = None
    assignee_email: Optional[str] = None
    reporter:       Optional[str] = None
    story_points:   Optional[int] = None
    labels:         Optional[List[str]] = None
    sprint_id:      Optional[str] = None
    due_date:       Optional[str] = None
    custom_fields:  Optional[dict] = None
    is_deleted:     bool = False
    created_at:     Optional[datetime] = None
    fix_version:    Optional[str] = None
    parent_key:     Optional[str] = None
    epic_key:       Optional[str] = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class StatusTransition(BaseModel):
    status: str


class NLCreateRequest(BaseModel):
    text: str


class AIAnalyzeRequest(BaseModel):
    text:            str
    available_users: List[str] = []


class AIAnalyzeOut(BaseModel):
    fields:         dict
    duplicates:     List[dict] = []
    has_duplicates: bool = False
    confidence:     Optional[float] = None


class CommentCreate(BaseModel):
    body:      str
    parent_id: Optional[str] = None


class CommentOut(BaseModel):
    id:          str
    ticket_id:   str
    author_id:   Optional[str] = None
    author_name: Optional[str] = None
    body:        str
    parent_id:   Optional[str] = None
    created_at:  datetime
    updated_at:  datetime
    is_deleted:  bool = False

    model_config = {"from_attributes": True}


class AttachmentOut(BaseModel):
    id:          str
    ticket_id:   str
    filename:    str
    filepath:    str
    url:         Optional[str] = None
    size_bytes:  Optional[int] = None
    uploaded_by: Optional[str] = None
    created_at:  datetime

    model_config = {"from_attributes": True}


class WorklogOut(BaseModel):
    id:       str
    author:   Optional[str] = None
    author_email: Optional[str] = None
    log_date: Optional[str] = None
    hours:    float
    comment:  Optional[str] = None

    model_config = {"from_attributes": True}


class TicketLinkCreate(BaseModel):
    link_type:  str
    target_key: str


class TicketLinkOut(BaseModel):
    id:             str
    source_ticket_id: str
    target_key:     str
    target_summary: Optional[str] = None
    link_type:      str
    created_at:     datetime

    model_config = {"from_attributes": True}
