"""
main.py — FastAPI application with all endpoints.

Run:
  pip install -r requirements.txt
  python -m uvicorn main:app --reload --port 8000
"""

from dotenv import load_dotenv
load_dotenv()

import os
from datetime import datetime, timedelta, date as date_type
from collections import defaultdict
from typing import Optional, List

from fastapi import FastAPI, Query, HTTPException, Depends, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler

from database import (
    get_db, create_tables,
    Organisation, User, OtpCode, JiraTicket, Worklog, ManualEntry, SyncLog,
    gen_uuid,
)
from auth import (
    get_current_user, get_admin, require_role,
    hash_password, verify_password, create_jwt,
    send_invite_email,
)
from models import (
    LoginRequest, RequestOtpRequest, VerifyOtpRequest, TokenResponse, UserOut,
    OrgCreate, OrgUpdate, OrgOut,
    EmployeeSyncItem, EmployeeSyncRequest,
    InviteUserRequest, UpdateUserRequest,
    ManualEntryCreate, ManualEntryUpdate, ManualEntryOut, ManualEntryBulkCreate,
    ActivityItem, SyncStatusOut, FiltersOut,
    SummaryOut, SummaryByPod, SummaryByClient, SummaryByUser,
    TicketOut, TicketsOut, WorklogOut,
)
from sync import sync_org, sync_all_orgs, get_last_sync
from report_generator import generate_monthly_finance_report, generate_fy_engineering_report

DEV_MODE = os.getenv("DEV_MODE", "true").lower() == "true"

# ── App setup ──────────────────────────────────────────────────────────────────

app = FastAPI(title="Engineering Analytics Platform API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create tables on startup
@app.on_event("startup")
def startup():
    create_tables()
    _start_scheduler()


# ── Background scheduler ───────────────────────────────────────────────────────

def _start_scheduler():
    interval = int(os.getenv("SYNC_INTERVAL_MINUTES", "30"))
    scheduler = BackgroundScheduler()
    scheduler.add_job(sync_all_orgs, "interval", minutes=interval, id="jira_sync")
    scheduler.start()
    print(f"⏰ Jira sync scheduled every {interval} minutes")


# ─────────────────────────────────────────────────────────────────────────────
# AUTH ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db:   Session = Depends(get_db),
):
    """
    Password login. Returns JWT on success.
    """
    user = (
        db.query(User)
        .filter(User.email == body.email.lower().strip(), User.status != "inactive")
        .first()
    )

    # No account found
    if not user:
        raise HTTPException(401, "Invalid email or password")

    # No password set yet — admin needs to set one
    if not user.password_hash:
        raise HTTPException(401, "Password not set. Contact your admin to set your password.")

    # Wrong password
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")

    # Success — update last login
    user.status     = "active"
    user.last_login = datetime.utcnow()
    db.commit()

    token = create_jwt(user)
    return TokenResponse(
        access_token = token,
        user         = UserOut.model_validate(user),
    )


@app.post("/api/auth/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """JWT is stateless — client discards the token. Just return success."""
    return {"message": "Logged out"}


@app.get("/api/auth/me", response_model=UserOut)
def get_me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@app.post("/api/auth/set-password")
def set_password(
    body: dict,
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    """User sets or changes their own password."""
    new_password = body.get("password", "").strip()
    if len(new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    user.password_hash = hash_password(new_password)
    db.commit()
    return {"message": "Password updated successfully"}


@app.post("/api/users/{user_id}/set-password")
def admin_set_password(
    user_id: str,
    body:    dict,
    admin:   User = Depends(get_admin),
    db:      Session = Depends(get_db),
):
    """Admin sets password for any user in the org."""
    target = db.query(User).filter(
        User.id == user_id, User.org_id == admin.org_id
    ).first()
    if not target:
        raise HTTPException(404, "User not found")

    new_password = body.get("password", "").strip()
    if len(new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")

    target.password_hash = hash_password(new_password)
    target.status        = "active"
    db.commit()
    return {"message": f"Password set for {target.name}"}


# ─────────────────────────────────────────────────────────────────────────────
# USER MANAGEMENT (Admin only)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/users", response_model=List[UserOut])
def list_users(
    user: User = Depends(get_admin),
    db:   Session = Depends(get_db),
):
    return db.query(User).filter(User.org_id == user.org_id).all()


@app.post("/api/users/invite", response_model=UserOut)
def invite_user(
    body:   InviteUserRequest,
    admin:  User = Depends(get_admin),
    db:     Session = Depends(get_db),
):
    if body.role not in ["admin","engineering_manager","tech_lead","team_member","finance_viewer"]:
        raise HTTPException(400, f"Invalid role: {body.role}")

    existing = db.query(User).filter(
        User.org_id == admin.org_id, User.email == body.email.lower()
    ).first()
    if existing:
        raise HTTPException(409, "A user with this email already exists in your organisation")

    org  = db.query(Organisation).filter(Organisation.id == admin.org_id).first()
    new_user = User(
        id            = gen_uuid(),
        org_id        = admin.org_id,
        name          = body.name,
        email         = body.email.lower(),
        role          = body.role,
        pod           = body.pod,
        password_hash = hash_password(body.password) if body.password else None,
        status        = "active" if body.password else "pending",
        invited_by    = admin.id,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    send_invite_email(new_user.email, new_user.name, admin.name, org.name if org else "your organisation")
    return UserOut.model_validate(new_user)


@app.put("/api/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    body:    UpdateUserRequest,
    admin:   User = Depends(get_admin),
    db:      Session = Depends(get_db),
):
    target = db.query(User).filter(
        User.id == user_id, User.org_id == admin.org_id
    ).first()
    if not target:
        raise HTTPException(404, "User not found")

    if body.name:   target.name   = body.name
    if body.role:   target.role   = body.role
    if body.pod is not None: target.pod = body.pod
    if body.status: target.status = body.status

    db.commit()
    db.refresh(target)
    return UserOut.model_validate(target)


@app.delete("/api/users/{user_id}")
def delete_user(
    user_id: str,
    admin:   User = Depends(get_admin),
    db:      Session = Depends(get_db),
):
    target = db.query(User).filter(
        User.id == user_id, User.org_id == admin.org_id
    ).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == admin.id:
        raise HTTPException(400, "Cannot delete your own account")
    target.status = "inactive"
    db.commit()
    return {"message": "User deactivated"}


# ─────────────────────────────────────────────────────────────────────────────
# SETTINGS (Admin only)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/settings", response_model=OrgOut)
def get_settings(
    admin: User = Depends(get_admin),
    db:    Session = Depends(get_db),
):
    org = db.query(Organisation).filter(Organisation.id == admin.org_id).first()
    if not org:
        raise HTTPException(404, "Organisation not found")
    return OrgOut.model_validate(org)


@app.put("/api/settings/jira", response_model=OrgOut)
def update_jira_settings(
    body:  OrgUpdate,
    admin: User = Depends(get_admin),
    db:    Session = Depends(get_db),
):
    org = db.query(Organisation).filter(Organisation.id == admin.org_id).first()
    if not org:
        raise HTTPException(404, "Organisation not found")

    if body.name              is not None: org.name              = body.name
    if body.jira_url             is not None: org.jira_url             = body.jira_url
    if body.jira_email           is not None: org.jira_email           = body.jira_email
    if body.jira_api_token       is not None: org.jira_api_token       = body.jira_api_token
    if body.jira_project_key     is not None: org.jira_project_key     = body.jira_project_key
    if body.jira_client_field    is not None: org.jira_client_field    = body.jira_client_field
    if body.jira_pod_field       is not None: org.jira_pod_field       = body.jira_pod_field

    db.commit()
    db.refresh(org)
    return OrgOut.model_validate(org)


# ─────────────────────────────────────────────────────────────────────────────
# EMPLOYEE DIRECTORY SYNC  (from Keka data)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/employees/sync", response_model=List[UserOut])
def sync_employees(
    body:  EmployeeSyncRequest,
    admin: User = Depends(get_admin),
    db:    Session = Depends(get_db),
):
    """
    Bulk upsert employees from the Keka directory.
    Matches on email — creates new users or updates existing ones.
    Sets emp_no, title, pods (comma-separated), reporting_to, role.
    Does NOT overwrite passwords.
    """
    results = []
    for emp in body.employees:
        existing = db.query(User).filter(
            User.org_id == admin.org_id,
            User.email  == emp.email.lower()
        ).first()

        pods_str = ",".join(emp.pod)

        if existing:
            existing.name         = emp.name
            existing.emp_no       = emp.empNo
            existing.title        = emp.title
            existing.role         = emp.role
            existing.pod          = pods_str
            existing.pods         = pods_str
            existing.reporting_to = emp.reportingTo
            existing.status       = "active"
            results.append(existing)
        else:
            new_user = User(
                id           = gen_uuid(),
                org_id       = admin.org_id,
                name         = emp.name,
                email        = emp.email.lower(),
                role         = emp.role,
                pod          = pods_str,
                pods         = pods_str,
                emp_no       = emp.empNo,
                title        = emp.title,
                reporting_to = emp.reportingTo,
                status       = "active",
            )
            db.add(new_user)
            results.append(new_user)

    db.commit()
    for u in results:
        db.refresh(u)
    return [UserOut.model_validate(u) for u in results]


@app.get("/api/team")
def get_team(
    current_user: User = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    """
    Returns team members visible to the current user based on role:
    - admin / engineering_manager: sees everyone in the org
    - tech_lead: sees themselves + all direct reportees (by reporting_to = their emp_no)
    - team_member: sees only themselves
    Also returns available pods scoped to the user's own pod access.
    """
    org_id = current_user.org_id

    # Get all active users in org
    all_users = db.query(User).filter(
        User.org_id == org_id,
        User.status == "active",
        User.emp_no != None,          # only synced employees
    ).all()

    user_emp_no = current_user.emp_no

    if current_user.role in ("admin", "engineering_manager"):
        visible = all_users

    elif current_user.role == "tech_lead":
        # Self + all users whose reporting_to == my emp_no (recursively 1 level)
        direct_reports = {u for u in all_users if u.reporting_to == user_emp_no}
        visible = [current_user] + list(direct_reports)

    else:
        # team_member — only self
        visible = [current_user]

    # Collect all pods this user has access to
    user_pods = [p.strip() for p in (current_user.pod or "").split(",") if p.strip()]

    def user_to_dict(u: User):
        u_pods = [p.strip() for p in (u.pod or "").split(",") if p.strip()]
        # Get manager name
        manager = None
        if u.reporting_to:
            mgr = next((x for x in all_users if x.emp_no == u.reporting_to), None)
            if mgr:
                manager = mgr.name
        return {
            "id":           u.id,
            "emp_no":       u.emp_no,
            "name":         u.name,
            "email":        u.email,
            "title":        u.title,
            "role":         u.role,
            "pods":         u_pods,
            "reporting_to": u.reporting_to,
            "manager":      manager,
            "location":     None,
            "status":       u.status,
        }

    return {
        "members":    [user_to_dict(u) for u in visible],
        "total":      len(visible),
        "user_pods":  user_pods,
    }


# ─────────────────────────────────────────────────────────────────────────────
# JIRA SYNC
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/sync")
def trigger_sync(
    background_tasks: BackgroundTasks,
    admin: User = Depends(get_admin),
    db:    Session = Depends(get_db),
):
    """Trigger a manual Jira sync. Runs in background so request returns immediately."""
    org = db.query(Organisation).filter(Organisation.id == admin.org_id).first()
    if not org:
        raise HTTPException(404, "Organisation not found")

    def run():
        from database import SessionLocal
        session = SessionLocal()
        try:
            sync_org(org, session)
        finally:
            session.close()

    background_tasks.add_task(run)
    return {"message": "Sync started in background"}


@app.get("/api/sync/status", response_model=SyncStatusOut)
def sync_status(
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    last = get_last_sync(user.org_id, db)
    if not last:
        return SyncStatusOut(last_sync=None, status=None, tickets_synced=None,
                             worklogs_synced=None, error=None, minutes_ago=None)
    minutes_ago = None
    if last.finished_at:
        diff = datetime.utcnow() - last.finished_at
        minutes_ago = int(diff.total_seconds() / 60)

    return SyncStatusOut(
        last_sync       = last.finished_at or last.started_at,
        status          = last.status,
        tickets_synced  = last.tickets_synced,
        worklogs_synced = last.worklogs_synced,
        error           = last.error,
        minutes_ago     = minutes_ago,
    )


# ─────────────────────────────────────────────────────────────────────────────
# FILTERS  (dropdown options — from DB, fast)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/filters", response_model=FiltersOut)
def get_filters(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org_id = user.org_id
    org    = db.query(Organisation).filter(Organisation.id == org_id).first()
    base   = db.query(JiraTicket).filter(JiraTicket.org_id == org_id)

    # Apply active project filter for users/clients/pods
    # (so sidebar shows only relevant PODs and clients for active projects)
    if org and org.jira_project_key:
        active = [p.strip() for p in org.jira_project_key.split(",") if p.strip()]
        if active:
            base = base.filter(JiraTicket.project_key.in_(active))

    # Scope for tech_lead / team_member
    if user.role in ("tech_lead", "team_member") and user.pod:
        base = base.filter(JiraTicket.pod == user.pod)

    tickets = base.all()

    # Projects list: always return ALL projects (unfiltered)
    # so the Settings page can show all available projects to pick from
    all_tickets = db.query(JiraTicket).filter(JiraTicket.org_id == org_id).all()

    return FiltersOut(
        users    = sorted(set(t.assignee    for t in tickets     if t.assignee)),
        clients  = sorted(set(t.client      for t in tickets     if t.client)),
        pods     = sorted(set(t.pod         for t in tickets     if t.pod)),
        projects = sorted(set(t.project_key for t in all_tickets if t.project_key)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY / KPIs  (from DB)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/summary", response_model=SummaryOut)
def get_summary(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    user_filter: Optional[str] = Query(None, alias="user"),
    client:    Optional[str] = Query(None),
    pod:       Optional[str] = Query(None),
    project:   Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tickets = _query_tickets(
        db, current_user.org_id, current_user,
        date_from, date_to, user_filter, client, pod, project
    )
    return _build_summary(tickets)


# ─────────────────────────────────────────────────────────────────────────────
# TICKETS  (from DB — fast, no live Jira call)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/tickets", response_model=TicketsOut)
def get_tickets(
    date_from: Optional[str] = Query(None),
    date_to:   Optional[str] = Query(None),
    user_filter: Optional[str] = Query(None, alias="user"),
    client:    Optional[str] = Query(None),
    pod:       Optional[str] = Query(None),
    project:   Optional[str] = Query(None),
    page:      int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Finance viewers cannot see ticket-level data
    if current_user.role == "finance_viewer":
        raise HTTPException(403, "Finance viewers cannot access ticket details")

    tickets = _query_tickets(
        db, current_user.org_id, current_user,
        date_from, date_to, user_filter, client, pod, project
    )
    total  = len(tickets)
    start  = (page - 1) * page_size
    paged  = tickets[start:start + page_size]

    return TicketsOut(
        tickets = [_ticket_to_out(t, for_user=user_filter) for t in paged],
        count   = total,
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENGINEER STATS  (used by drawer — matches team page summary exactly)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/engineer-stats")
def get_engineer_stats(
    user_filter:  str = Query(..., alias="user"),
    date_from:    Optional[str] = Query(None),
    date_to:      Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns hours + ticket count for a specific engineer
    including both Jira worklogs and manual entries.
    """
    org_id = current_user.org_id
    org    = db.query(Organisation).filter(Organisation.id == org_id).first()

    # ── Jira tickets + worklogs ──
    from sqlalchemy import or_
    q = (db.query(JiraTicket)
         .filter(JiraTicket.org_id == org_id)
         .filter(or_(
             JiraTicket.assignee == user_filter,
             JiraTicket.worklogs.any(Worklog.author == user_filter)
         )))

    if org and org.jira_project_key:
        active = [p.strip() for p in org.jira_project_key.split(",") if p.strip()]
        if active:
            q = q.filter(JiraTicket.project_key.in_(active))
    if date_from:
        q = q.filter(JiraTicket.jira_updated >= date_from)
    if date_to:
        q = q.filter(JiraTicket.jira_updated <= date_to)

    tickets     = q.all()
    jira_hours  = 0
    ticket_keys = set()
    active_days = set()
    clients     = set()

    for t in tickets:
        if t.worklogs:
            for wl in t.worklogs:
                if wl.author == user_filter:
                    jira_hours += wl.hours or 0
                    ticket_keys.add(t.jira_key)
                    if wl.log_date: active_days.add(str(wl.log_date))
                    if t.client:    clients.add(t.client)
        else:
            if t.assignee == user_filter:
                jira_hours += t.hours_spent or 0
                ticket_keys.add(t.jira_key)
                if t.jira_updated: active_days.add(str(t.jira_updated))
                if t.client:       clients.add(t.client)

    # ── Manual entries ──
    target_user = db.query(User).filter(
        User.org_id == org_id, User.name == user_filter
    ).first()

    manual_hours   = 0
    manual_entries = 0

    if target_user:
        me_q = db.query(ManualEntry).filter(
            ManualEntry.org_id  == org_id,
            ManualEntry.user_id == target_user.id,
            ManualEntry.status  == "confirmed",
        )
        if date_from: me_q = me_q.filter(ManualEntry.entry_date >= date_from)
        if date_to:   me_q = me_q.filter(ManualEntry.entry_date <= date_to)

        for me in me_q.all():
            manual_hours   += me.hours or 0
            manual_entries += 1
            if me.entry_date: active_days.add(str(me.entry_date))
            if me.client:     clients.add(me.client)

    return {
        "user":           user_filter,
        "hours":          round(jira_hours + manual_hours, 2),
        "jira_hours":     round(jira_hours, 2),
        "manual_hours":   round(manual_hours, 2),
        "tickets":        len(ticket_keys),
        "manual_entries": manual_entries,
        "active_days":    len(active_days),
        "clients":        len(clients),
    }


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY FEED  (Jira + manual entries combined, per user/date)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/activity", response_model=List[ActivityItem])
def get_activity(
    user_filter: Optional[str] = Query(None, alias="user"),
    date_from:   Optional[str] = Query(None),
    date_to:     Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns all Jira worklogs + manual entries for a user/date range,
    merged and sorted by date descending.
    Used by the Team page engineer detail drawer.
    """
    org_id = current_user.org_id

    # Resolve target — if user_filter provided use it as name,
    # otherwise use the current user's email to match Jira records
    if user_filter:
        target_name  = user_filter
        target_email = None
        # Try to find the user's email from name
        target_user = db.query(User).filter(
            User.org_id == org_id, User.name == user_filter
        ).first()
        if target_user:
            target_email = target_user.email
    else:
        target_name  = current_user.name
        target_email = current_user.email

    items: List[ActivityItem] = []

    # ── Jira worklogs — match by email first, fall back to name ──
    wl_query = (
        db.query(Worklog, JiraTicket)
        .join(JiraTicket, Worklog.ticket_id == JiraTicket.id)
        .filter(JiraTicket.org_id == org_id)
    )
    if target_email:
        wl_query = wl_query.filter(Worklog.author_email == target_email)
    elif target_name:
        wl_query = wl_query.filter(Worklog.author == target_name)
    if date_from:
        wl_query = wl_query.filter(Worklog.log_date >= date_from)
    if date_to:
        wl_query = wl_query.filter(Worklog.log_date <= date_to)

    for wl, ticket in wl_query.all():
        items.append(ActivityItem(
            id         = wl.id,
            source     = "jira",
            date       = wl.log_date or ticket.jira_updated,
            activity   = ticket.summary,
            hours      = wl.hours,
            pod        = ticket.pod,
            client     = ticket.client,
            entry_type = ticket.issue_type,
            jira_key   = ticket.jira_key,
            url        = ticket.url,
            notes      = wl.comment,
            user_name  = wl.author or target_name,
            user_id    = "",
        ))

    # Also include estimate-based tickets (no worklogs) — match by email
    est_tickets = (
        db.query(JiraTicket)
        .filter(
            JiraTicket.org_id == org_id,
            ~JiraTicket.worklogs.any(),
            JiraTicket.hours_spent > 0,
        )
    )
    if target_email:
        est_tickets = est_tickets.filter(JiraTicket.assignee_email == target_email)
    elif target_name:
        est_tickets = est_tickets.filter(JiraTicket.assignee == target_name)
    if date_from:
        est_tickets = est_tickets.filter(JiraTicket.jira_updated >= date_from)
    if date_to:
        est_tickets = est_tickets.filter(JiraTicket.jira_updated <= date_to)

    for ticket in est_tickets.all():
        items.append(ActivityItem(
            id         = ticket.id,
            source     = "jira",
            date       = ticket.jira_updated,
            activity   = ticket.summary,
            hours      = ticket.hours_spent,
            pod        = ticket.pod,
            client     = ticket.client,
            entry_type = ticket.issue_type,
            jira_key   = ticket.jira_key,
            url        = ticket.url,
            notes      = None,
            user_name  = ticket.assignee or target,
            user_id    = "",
        ))

    # ── Manual entries ──
    me_query = (
        db.query(ManualEntry, User)
        .join(User, ManualEntry.user_id == User.id)
        .filter(ManualEntry.org_id == org_id)
    )
    if target_email:
        me_query = me_query.filter(User.email == target_email)
    elif target_name:
        me_query = me_query.filter(User.name == target_name)
    if date_from:
        me_query = me_query.filter(ManualEntry.entry_date >= date_from)
    if date_to:
        me_query = me_query.filter(ManualEntry.entry_date <= date_to)

    for entry, entry_user in me_query.all():
        items.append(ActivityItem(
            id         = entry.id,
            source     = "manual",
            date       = entry.entry_date,
            activity   = entry.activity,
            hours      = entry.hours,
            pod        = entry.pod,
            client     = entry.client,
            entry_type = entry.entry_type,
            jira_key   = None,
            url        = None,
            notes      = entry.notes,
            user_name  = entry_user.name,
            user_id    = entry_user.id,
        ))

    # Sort by date descending
    items.sort(key=lambda x: x.date or date_type.min, reverse=True)
    return items


# ─────────────────────────────────────────────────────────────────────────────
# MANUAL ENTRIES
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/manual-entries", response_model=List[ManualEntryOut])
def create_manual_entries(
    body:         ManualEntryBulkCreate,
    current_user: User = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    """Save all confirmed entries from the AI Time Entry screen at once."""
    if current_user.role == "finance_viewer":
        raise HTTPException(403, "Finance viewers cannot create time entries")

    VALID_TYPES = {"Meeting", "Bugs", "Feature", "Program Management"}

    created = []
    for e in body.entries:
        safe_type = e.entry_type if e.entry_type in VALID_TYPES else "Other"

        entry = ManualEntry(
            id           = gen_uuid(),
            user_id      = current_user.id,
            org_id       = current_user.org_id,
            entry_date   = e.entry_date,
            activity     = e.activity,
            hours        = e.hours,
            pod          = e.pod,
            client       = e.client,
            entry_type   = safe_type,
            notes        = e.notes,
            ai_raw_input = body.ai_raw_input or e.ai_raw_input,
            ai_parsed    = e.ai_parsed,
            status       = "confirmed",
        )
        db.add(entry)
        created.append(entry)

    db.commit()
    for e in created:
        db.refresh(e)

    return [
        ManualEntryOut(
            **{k: getattr(e, k) for k in ManualEntryOut.model_fields if hasattr(e, k)},
            user_name = current_user.name,
        )
        for e in created
    ]


@app.get("/api/manual-entries", response_model=List[ManualEntryOut])
def get_manual_entries(
    date_from:   Optional[str] = Query(None),
    date_to:     Optional[str] = Query(None),
    user_filter: Optional[str] = Query(None, alias="user"),
    pod:         Optional[str] = Query(None),
    client:      Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(ManualEntry, User)
        .join(User, ManualEntry.user_id == User.id)
        .filter(ManualEntry.org_id == current_user.org_id)
    )

    # Team members / tech leads only see their own entries
    if current_user.role in ("team_member", "tech_lead"):
        query = query.filter(ManualEntry.user_id == current_user.id)
    elif user_filter:
        query = query.filter(User.name == user_filter)

    if date_from: query = query.filter(ManualEntry.entry_date >= date_from)
    if date_to:   query = query.filter(ManualEntry.entry_date <= date_to)
    if pod:       query = query.filter(ManualEntry.pod    == pod)
    if client:    query = query.filter(ManualEntry.client == client)

    results = query.order_by(ManualEntry.entry_date.desc()).all()

    return [
        ManualEntryOut(
            **{k: getattr(entry, k) for k in ManualEntryOut.model_fields if hasattr(entry, k)},
            user_name = u.name,
        )
        for entry, u in results
    ]


@app.put("/api/manual-entries/{entry_id}", response_model=ManualEntryOut)
def update_manual_entry(
    entry_id:     str,
    body:         ManualEntryUpdate,
    current_user: User = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    entry = db.query(ManualEntry).filter(
        ManualEntry.id     == entry_id,
        ManualEntry.org_id == current_user.org_id,
    ).first()
    if not entry:
        raise HTTPException(404, "Entry not found")

    # Only the owner or admin can edit
    if entry.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "You can only edit your own entries")

    for field in ["entry_date","activity","hours","pod","client","entry_type","notes","status"]:
        val = getattr(body, field, None)
        if val is not None:
            setattr(entry, field, val)

    db.commit()
    db.refresh(entry)
    user = db.query(User).filter(User.id == entry.user_id).first()
    return ManualEntryOut(
        **{k: getattr(entry, k) for k in ManualEntryOut.model_fields if hasattr(entry, k)},
        user_name = user.name if user else None,
    )


@app.delete("/api/manual-entries/{entry_id}")
def delete_manual_entry(
    entry_id:     str,
    current_user: User = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    entry = db.query(ManualEntry).filter(
        ManualEntry.id     == entry_id,
        ManualEntry.org_id == current_user.org_id,
    ).first()
    if not entry:
        raise HTTPException(404, "Entry not found")
    if entry.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "You can only delete your own entries")

    db.delete(entry)
    db.commit()
    return {"message": "Entry deleted"}


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT  (merges Jira tickets + manual entries)
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/api/export/monthly")
def export_monthly(
    date_from:   Optional[str] = Query(None),
    date_to:     Optional[str] = Query(None),
    month_label: Optional[str] = Query(None),
    user_filter: Optional[str] = Query(None, alias="user"),
    client:      Optional[str] = Query(None),
    pod:         Optional[str] = Query(None),
    project:     Optional[str] = Query(None),
    current_user: User = Depends(require_role("admin","engineering_manager","finance_viewer")),
    db: Session = Depends(get_db),
):
    if not month_label:
        month_label = datetime.now().strftime("%b %y").upper()

    tickets = _query_tickets(db, current_user.org_id, current_user,
                             date_from, date_to, user_filter, client, pod, project)
    rows    = _tickets_to_flat_rows(tickets)

    # Add manual entries to the raw rows
    me_rows = _get_manual_rows(db, current_user.org_id, date_from, date_to,
                                user_filter, pod, client)
    rows.extend(me_rows)

    path = generate_monthly_finance_report(rows, tickets, month_label,
                                           date_from=date_from, date_to=date_to)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"timesheet_{month_label.replace(' ','_')}.xlsx",
    )


@app.get("/api/export/fy")
def export_fy(
    date_from:   Optional[str] = Query(None),
    date_to:     Optional[str] = Query(None),
    fy_label:    str = Query("2024-2025"),
    user_filter: Optional[str] = Query(None, alias="user"),
    client:      Optional[str] = Query(None),
    pod:         Optional[str] = Query(None),
    project:     Optional[str] = Query(None),
    current_user: User = Depends(require_role("admin","engineering_manager","finance_viewer")),
    db: Session = Depends(get_db),
):
    tickets = _query_tickets(db, current_user.org_id, current_user,
                             date_from, date_to, user_filter, client, pod, project)

    # Convert DB rows back to the dict format report_generator expects
    ticket_dicts = [_ticket_to_dict(t) for t in tickets]

    path = generate_fy_engineering_report(ticket_dicts, fy_label=fy_label)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"engineering_timesheet_FY_{fy_label}.xlsx",
    )


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0", "dev_mode": DEV_MODE}


# ─────────────────────────────────────────────────────────────────────────────
# SETUP ENDPOINT — create first org + admin user (run once)
# ─────────────────────────────────────────────────────────────────────────────

@app.post("/api/setup")
def setup(body: OrgCreate, db: Session = Depends(get_db)):
    """
    First-run setup. Creates the organisation and a default admin user.
    Disable or delete this endpoint after setup is complete.
    """
    if db.query(Organisation).count() > 0:
        raise HTTPException(400, "Setup already complete. This endpoint is disabled.")

    org = Organisation(
        id                = gen_uuid(),
        name              = body.name,
        jira_url          = body.jira_url,
        jira_email        = body.jira_email,
        jira_api_token    = body.jira_api_token,
        jira_project_key  = body.jira_project_key,
        jira_client_field = body.jira_client_field,
        jira_pod_field    = body.jira_pod_field,
    )
    db.add(org)
    db.flush()

    admin = User(
        id            = gen_uuid(),
        org_id        = org.id,
        name          = "Admin",
        email         = body.jira_email.lower(),
        role          = "admin",
        status        = "active",
        password_hash = hash_password(body.admin_password) if hasattr(body, "admin_password") and body.admin_password else None,
    )
    db.add(admin)
    db.commit()

    return {
        "message":  "Setup complete",
        "org_id":   org.id,
        "admin_id": admin.id,
        "email":    admin.email,
        "note":     "Use POST /api/auth/request-otp to log in",
    }


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _query_tickets(
    db, org_id, current_user,
    date_from=None, date_to=None,
    user=None, client=None, pod=None, project=None,
):
    """
    Query JiraTicket rows with filters + role scoping.

    Date range logic:
    - When a specific user is requested (user param or team_member role),
      use worklog.log_date so tickets logged in the period are included
      even if jira_updated is outside the range.
    - For general queries (admin/manager, no user filter), use jira_updated.
    """
    from sqlalchemy import or_

    q = db.query(JiraTicket).filter(JiraTicket.org_id == org_id)

    # ── Org-level project filter ──────────────────────────────────────────────
    org = db.query(Organisation).filter(Organisation.id == org_id).first()
    if org and org.jira_project_key:
        active = [p.strip() for p in org.jira_project_key.split(",") if p.strip()]
        if active:
            q = q.filter(JiraTicket.project_key.in_(active))

    # ── Static filters ────────────────────────────────────────────────────────
    if client:  q = q.filter(JiraTicket.client == client)
    if project: q = q.filter(JiraTicket.project_key == project)
    if pod:
        pod_list = [p.strip() for p in pod.split(",") if p.strip()]
        q = q.filter(JiraTicket.pod.in_(pod_list) if len(pod_list) > 1 else JiraTicket.pod == pod_list[0])

    # ── Determine the target user ─────────────────────────────────────────────
    # explicit user param takes precedence, then role-based scoping
    target_user = user  # explicit filter (e.g. manager viewing a team member)

    if not target_user and current_user.role == "team_member":
        target_user = current_user.name  # team_member always scoped to self

    # ── Pod scoping for tech_lead ─────────────────────────────────────────────
    if current_user.role == "tech_lead" and current_user.pod:
        lead_pods = [p.strip() for p in current_user.pod.split(",") if p.strip()]
        if lead_pods:
            q = q.filter(JiraTicket.pod.in_(lead_pods))

    # ── User scoping + date filter ────────────────────────────────────────────
    if target_user:
        # Include tickets where user is assignee OR has worklogs
        q = q.filter(or_(
            JiraTicket.assignee == target_user,
            JiraTicket.worklogs.any(Worklog.author == target_user)
        ))
        # Date filter: match worklog date (user may log on old tickets)
        if date_from or date_to:
            wl_cond = Worklog.author == target_user
            if date_from: wl_cond = wl_cond & (Worklog.log_date >= date_from)
            if date_to:   wl_cond = wl_cond & (Worklog.log_date <= date_to)

            assigned_cond = JiraTicket.assignee == target_user
            if date_from: assigned_cond = assigned_cond & (JiraTicket.jira_updated >= date_from)
            if date_to:   assigned_cond = assigned_cond & (JiraTicket.jira_updated <= date_to)

            q = q.filter(or_(
                JiraTicket.worklogs.any(wl_cond),
                assigned_cond
            ))
    else:
        # No user scope — admin/manager general query — use jira_updated
        if date_from: q = q.filter(JiraTicket.jira_updated >= date_from)
        if date_to:   q = q.filter(JiraTicket.jira_updated <= date_to)

    return q.order_by(JiraTicket.jira_updated.desc()).all()


def _build_summary(tickets) -> SummaryOut:
    by_pod    = defaultdict(lambda: {"hours": 0, "tickets": set(), "clients": set()})
    by_client = defaultdict(lambda: {"hours": 0, "tickets": set(), "users": set()})
    by_user   = defaultdict(lambda: {"hours": 0, "tickets": set(), "clients": set()})

    total_hours = 0

    for t in tickets:
        if t.worklogs:
            # Attribute hours to each individual worklog author
            for wl in t.worklogs:
                h      = wl.hours or 0
                author = wl.author or t.assignee
                total_hours += h

                if t.pod:
                    by_pod[t.pod]["hours"] += h
                    by_pod[t.pod]["tickets"].add(t.jira_key)
                    if t.client: by_pod[t.pod]["clients"].add(t.client)
                if t.client:
                    by_client[t.client]["hours"] += h
                    by_client[t.client]["tickets"].add(t.jira_key)
                    if author: by_client[t.client]["users"].add(author)
                if author:
                    by_user[author]["hours"] += h
                    by_user[author]["tickets"].add(t.jira_key)
                    if t.client: by_user[author]["clients"].add(t.client)
        else:
            # No worklogs — fall back to assignee
            h = t.hours_spent or 0
            total_hours += h
            if t.pod:
                by_pod[t.pod]["hours"] += h
                by_pod[t.pod]["tickets"].add(t.jira_key)
                if t.client: by_pod[t.pod]["clients"].add(t.client)
            if t.client:
                by_client[t.client]["hours"] += h
                by_client[t.client]["tickets"].add(t.jira_key)
                if t.assignee: by_client[t.client]["users"].add(t.assignee)
            if t.assignee:
                by_user[t.assignee]["hours"] += h
                by_user[t.assignee]["tickets"].add(t.jira_key)
                if t.client: by_user[t.assignee]["clients"].add(t.client)

    return SummaryOut(
        by_pod    = sorted([SummaryByPod(pod=k, hours=round(v["hours"],2),
                            tickets=len(v["tickets"]), clients=list(v["clients"]))
                            for k,v in by_pod.items()], key=lambda x:-x.hours),
        by_client = sorted([SummaryByClient(client=k, hours=round(v["hours"],2),
                            tickets=len(v["tickets"]), users=list(v["users"]))
                            for k,v in by_client.items()], key=lambda x:-x.hours),
        by_user   = sorted([SummaryByUser(user=k, hours=round(v["hours"],2),
                            tickets=len(v["tickets"]), clients=list(v["clients"]))
                            for k,v in by_user.items()], key=lambda x:-x.hours),
        total_tickets = len(tickets),
        total_hours   = round(total_hours, 2),
    )


def _ticket_to_out(t: JiraTicket, for_user: str = None) -> TicketOut:
    # If viewing for a specific user, show only their logged hours
    if for_user and t.worklogs:
        user_hours = sum(wl.hours or 0 for wl in t.worklogs if wl.author == for_user)
    else:
        user_hours = t.hours_spent or 0

    return TicketOut(
        key                      = t.jira_key,
        project_key              = t.project_key,
        project_name             = t.project_name,
        summary                  = t.summary,
        assignee                 = t.assignee,
        assignee_email           = t.assignee_email,
        status                   = t.status,
        client                   = t.client,
        pod                      = t.pod,
        issue_type               = t.issue_type,
        priority                 = t.priority,
        hours_spent              = user_hours,
        original_estimate_hours  = t.original_estimate_hours or 0,
        remaining_estimate_hours = t.remaining_estimate_hours or 0,
        created                  = str(t.jira_created) if t.jira_created else None,
        updated                  = str(t.jira_updated) if t.jira_updated else None,
        url                      = t.url,
        worklogs = [
            WorklogOut(
                author  = w.author,
                email   = w.author_email,
                date    = str(w.log_date) if w.log_date else None,
                hours   = w.hours or 0,
                comment = w.comment,
            ) for w in t.worklogs
        ],
    )


def _ticket_to_dict(t: JiraTicket) -> dict:
    """Convert DB row back to dict format that report_generator.py expects."""
    return {
        "key":                      t.jira_key,
        "project_key":              t.project_key,
        "project_name":             t.project_name,
        "summary":                  t.summary,
        "assignee":                 t.assignee or "Unassigned",
        "assignee_email":           t.assignee_email or "",
        "status":                   t.status or "",
        "client":                   t.client or "Not Set",
        "pod":                      t.pod or "Not Set",
        "issue_type":               t.issue_type or "",
        "priority":                 t.priority or "",
        "hours_spent":              t.hours_spent or 0,
        "original_estimate_hours":  t.original_estimate_hours or 0,
        "remaining_estimate_hours": t.remaining_estimate_hours or 0,
        "created":                  str(t.jira_created) if t.jira_created else "",
        "updated":                  str(t.jira_updated) if t.jira_updated else "",
        "url":                      t.url or "",
        "worklogs": [
            {"author": w.author, "email": w.author_email or "",
             "date": str(w.log_date) if w.log_date else "",
             "hours": w.hours or 0, "comment": w.comment or ""}
            for w in t.worklogs
        ],
    }


def _tickets_to_flat_rows(tickets) -> list:
    """Expand tickets/worklogs to flat rows for monthly export."""
    rows = []
    for t in tickets:
        if t.worklogs:
            for w in t.worklogs:
                rows.append({
                    "name":    w.author,
                    "pod":     t.pod,
                    "date":    str(w.log_date) if w.log_date else str(t.jira_updated),
                    "module":  t.pod,
                    "feature": t.summary,
                    "type":    t.issue_type or "Feature",
                    "client":  t.client,
                    "hours":   w.hours or 0,
                    "jira":    t.jira_key,
                    "remark":  w.comment or "",
                })
        else:
            rows.append({
                "name":    t.assignee,
                "pod":     t.pod,
                "date":    str(t.jira_updated) if t.jira_updated else "",
                "module":  t.pod,
                "feature": t.summary,
                "type":    t.issue_type or "Feature",
                "client":  t.client,
                "hours":   t.hours_spent or 0,
                "jira":    t.jira_key,
                "remark":  "",
            })
    return rows


def _get_manual_rows(db, org_id, date_from, date_to, user, pod, client) -> list:
    """Get manual entries as flat rows for monthly export."""
    q = db.query(ManualEntry, User).join(User, ManualEntry.user_id == User.id)\
          .filter(ManualEntry.org_id == org_id, ManualEntry.status == "confirmed")
    if date_from: q = q.filter(ManualEntry.entry_date >= date_from)
    if date_to:   q = q.filter(ManualEntry.entry_date <= date_to)
    if user:      q = q.filter(User.name == user)
    if pod:       q = q.filter(ManualEntry.pod    == pod)
    if client:    q = q.filter(ManualEntry.client == client)

    rows = []
    for entry, u in q.all():
        rows.append({
            "name":    u.name,
            "pod":     entry.pod or "",
            "date":    str(entry.entry_date),
            "module":  entry.pod or "",
            "feature": entry.activity,
            "type":    entry.entry_type or "Meeting",
            "client":  entry.client or "",
            "hours":   entry.hours,
            "jira":    "",         # manual entries have no Jira key
            "remark":  entry.notes or "",
        })
    return rows


# ── Time Entry Parser ─────────────────────────────────────────────────────────

@app.post("/api/ai/parse-entries")
def parse_entries(
    body:         dict,
    current_user: User = Depends(get_current_user),
    db:           Session = Depends(get_db),
):
    """
    Parses natural language time entry text into structured entries.
    Uses the local parser (no external AI needed).
    Backend has full access to PODs, clients, and user context.
    """
    from local_parser import parse_time_entries
    from datetime import date as _date

    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "No text provided")

    # Get PODs and clients — use from request if provided, else fetch from DB
    pods    = body.get("pods",    [])
    clients = body.get("clients", [])

    if not pods or not clients:
        tickets = db.query(JiraTicket).filter(
            JiraTicket.org_id == current_user.org_id
        ).all()
        if not pods:
            pods    = sorted(set(t.pod    for t in tickets if t.pod))
        if not clients:
            clients = sorted(set(t.client for t in tickets if t.client))

    result = parse_time_entries(
        text    = text,
        pods    = pods,
        clients = clients,
        today   = _date.today(),
    )

    return result


# ── TEMP DEBUG — remove after fixing login ────────────────────────────────────
@app.post("/api/debug/login")
def debug_login(body: dict, db: Session = Depends(get_db)):
    import bcrypt
    email    = body.get("email", "").lower().strip()
    password = body.get("password", "")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        return {"error": "user not found", "email": email}

    return {
        "user_found":     True,
        "status":         user.status,
        "has_hash":       user.password_hash is not None,
        "hash_prefix":    user.password_hash[:20] if user.password_hash else None,
        "hash_len":       len(user.password_hash) if user.password_hash else 0,
        "bcrypt_check":   bcrypt.checkpw(password.encode(), user.password_hash.encode()) if user.password_hash else False,
        "password_tried": password,
    }