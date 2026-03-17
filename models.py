"""
models.py — Pydantic schemas for all request/response shapes.
"""

from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime


# ── Auth ───────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email:    EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    user:         "UserOut"

# Kept for backward compat
class RequestOtpRequest(BaseModel):
    email: EmailStr

class VerifyOtpRequest(BaseModel):
    email: EmailStr
    code:  str

class UserOut(BaseModel):
    id:           str
    name:         str
    email:        str
    role:         str
    pod:          Optional[str]      = None
    pods:         Optional[str]      = None
    emp_no:       Optional[str]      = None
    title:        Optional[str]      = None
    reporting_to: Optional[str]      = None
    status:       str
    org_id:       str
    last_login:   Optional[datetime] = None

    class Config:
        from_attributes = True

TokenResponse.model_rebuild()


# ── Organisation ───────────────────────────────────────────────────────────────

class OrgCreate(BaseModel):
    name:              str
    jira_url:          str
    jira_email:        EmailStr
    jira_api_token:    str
    jira_project_key:  Optional[str] = None
    jira_client_field: str = "customfield_10233"
    jira_pod_field:    str = "customfield_10193"

class OrgUpdate(BaseModel):
    name:                Optional[str]      = None
    jira_url:            Optional[str]      = None
    jira_email:          Optional[EmailStr] = None
    jira_api_token:      Optional[str]      = None
    jira_project_key:    Optional[str]      = None
    jira_client_field:   Optional[str]      = None
    jira_pod_field:      Optional[str]      = None

class OrgOut(BaseModel):
    id:                  str
    name:                str
    jira_url:            str
    jira_email:          str
    jira_project_key:    Optional[str] = None
    jira_client_field:   Optional[str] = None
    jira_pod_field:      Optional[str] = None
    created_at:          datetime

    class Config:
        from_attributes = True


# ── Users ──────────────────────────────────────────────────────────────────────

class EmployeeSyncItem(BaseModel):
    empNo:       str
    name:        str
    email:       str
    title:       str
    role:        str
    pod:         List[str]           # list of pod keys
    reportingTo: Optional[str] = None

class EmployeeSyncRequest(BaseModel):
    employees: List[EmployeeSyncItem]


class InviteUserRequest(BaseModel):
    name:     str
    email:    EmailStr
    role:     str
    pod:      Optional[str] = None
    password: Optional[str] = None  # admin sets initial password

class UpdateUserRequest(BaseModel):
    name:   Optional[str] = None
    role:   Optional[str] = None
    pod:    Optional[str] = None
    status: Optional[str] = None


# ── Manual Entries ─────────────────────────────────────────────────────────────

class ManualEntryCreate(BaseModel):
    entry_date:   date
    activity:     str
    hours:        float
    pod:          Optional[str] = None
    client:       Optional[str] = None
    entry_type:   str = "Meeting"
    notes:        Optional[str] = None
    ai_raw_input: Optional[str] = None   # original text from AI input box
    ai_parsed:    bool = True

class ManualEntryUpdate(BaseModel):
    entry_date:  Optional[date] = None
    activity:    Optional[str] = None
    hours:       Optional[float] = None
    pod:         Optional[str] = None
    client:      Optional[str] = None
    entry_type:  Optional[str] = None
    notes:       Optional[str] = None
    status:      Optional[str] = None

class ManualEntryOut(BaseModel):
    id:           str
    user_id:      str
    entry_date:   date
    activity:     str
    hours:        float
    pod:          Optional[str] = None
    client:       Optional[str] = None
    entry_type:   str
    notes:        Optional[str] = None
    ai_parsed:    bool
    status:       str
    created_at:   datetime
    # user name — joined from users table
    user_name:    Optional[str] = None

    class Config:
        from_attributes = True


# Bulk create — frontend sends all confirmed rows at once
class ManualEntryBulkCreate(BaseModel):
    entries:      List[ManualEntryCreate]
    ai_raw_input: Optional[str] = None  # shared raw input for the whole batch


# ── Activity feed ──────────────────────────────────────────────────────────────

class ActivityItem(BaseModel):
    id:         str
    source:     str          # "jira" | "manual"
    date:       date
    activity:   str          # ticket summary or manual activity name
    hours:      float
    pod:        Optional[str] = None
    client:     Optional[str] = None
    entry_type: Optional[str] = None  # issue_type for jira, entry_type for manual
    jira_key:   Optional[str] = None  # only for jira source
    url:        Optional[str] = None  # only for jira source
    notes:      Optional[str] = None  # only for manual source
    user_name:  str
    user_id:    str


# ── Sync ───────────────────────────────────────────────────────────────────────

class SyncStatusOut(BaseModel):
    last_sync:      Optional[datetime] = None
    status:         Optional[str] = None
    tickets_synced: Optional[int] = None
    worklogs_synced:Optional[int] = None
    error:          Optional[str] = None
    minutes_ago:    Optional[int] = None


# ── Filters (dropdown options) ─────────────────────────────────────────────────

class FiltersOut(BaseModel):
    users:    List[str]
    clients:  List[str]
    pods:     List[str]
    projects: List[str]


# ── Summary / KPIs ─────────────────────────────────────────────────────────────

class SummaryByPod(BaseModel):
    pod:     str
    hours:   float
    tickets: int
    clients: List[str]

class SummaryByClient(BaseModel):
    client:  str
    hours:   float
    tickets: int
    users:   List[str]

class SummaryByUser(BaseModel):
    user:        str
    hours:       float
    tickets:     int
    clients:     List[str]
    # org profile fields — populated from users table
    email:       Optional[str]      = None
    role:        Optional[str]      = None
    pod:         Optional[str]      = None
    title:       Optional[str]      = None
    status:      Optional[str]      = None
    manager:     Optional[str]      = None
    user_id:     Optional[str]      = None
    last_login:  Optional[str]      = None

class SummaryByIssueType(BaseModel):
    issue_type: str
    hours:      float
    tickets:    int
    pct:        float   # percentage of total hours

class SummaryOut(BaseModel):
    by_pod:        List[SummaryByPod]
    by_client:     List[SummaryByClient]
    by_user:       List[SummaryByUser]
    by_issue_type: List[SummaryByIssueType] = []
    total_tickets: int
    total_hours:   float


# ── Tickets ────────────────────────────────────────────────────────────────────

class WorklogOut(BaseModel):
    author:  str
    email:   Optional[str] = None
    date:    Optional[str] = None   # stored as string "YYYY-MM-DD"
    hours:   float
    comment: Optional[str] = None

class TicketOut(BaseModel):
    key:                      str
    project_key:              str
    project_name:             Optional[str] = None
    summary:                  str
    assignee:                 Optional[str] = None
    assignee_email:           Optional[str] = None
    status:                   Optional[str] = None
    client:                   Optional[str] = None
    pod:                      Optional[str] = None
    issue_type:               Optional[str] = None
    priority:                 Optional[str] = None
    hours_spent:              float
    original_estimate_hours:  float
    remaining_estimate_hours: float
    created:                  Optional[str] = None
    updated:                  Optional[str] = None
    url:                      Optional[str] = None
    worklogs:                 List[WorklogOut] = []

class TicketsOut(BaseModel):
    tickets: List[TicketOut]
    count:   int