from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


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
    story_points:   Optional[int] = None
    labels:         Optional[List[str]] = None
    sprint_id:      Optional[str] = None
    jira_key:       Optional[str] = None
    due_date:       Optional[str] = None


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
    story_points:   Optional[int] = None
    sprint_id:      Optional[str] = None
    due_date:       Optional[str] = None


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
    story_points:   Optional[int] = None
    labels:         Optional[List[str]] = None
    sprint_id:      Optional[str] = None
    due_date:       Optional[str] = None
    is_deleted:     bool = False
    created_at:     Optional[datetime] = None

    model_config = {"from_attributes": True}


class StatusTransition(BaseModel):
    status: str


class NLCreateRequest(BaseModel):
    text: str


class AIAnalyzeRequest(BaseModel):
    text: str


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
    size_bytes:  Optional[int] = None
    uploaded_by: Optional[str] = None
    created_at:  datetime

    model_config = {"from_attributes": True}
