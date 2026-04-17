"""
seeds/seed_anoop.py — Seed realistic data for Anoop Kumar Rai (anoop.rai@3scsolution.com).

Creates:
  - 8 tickets assigned to Anoop in SNOP and EDM pods
  - Worklogs for current + previous month (so dashboard hours show up)
  - 5 manual entries (meetings, feature work)

Usage:
  cd trackly-backend
  source venv/bin/activate
  python seeds/seed_anoop.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from datetime import date, timedelta
from app.core.database import SessionLocal
from app.models.organisation import Organisation
from app.models.user import User
from app.models.ticket import JiraTicket, Worklog
from app.models.manual_entry import ManualEntry
from app.models.base import gen_uuid

db = SessionLocal()

org  = db.query(Organisation).first()
if not org:
    print("❌ No organisation found")
    sys.exit(1)

anoop = db.query(User).filter(
    User.org_id == org.id,
    User.email  == "anoop.rai@3scsolution.com",
).first()

if not anoop:
    print("❌ User anoop.rai@3scsolution.com not found")
    sys.exit(1)

print(f"Org:   {org.name}")
print(f"User:  {anoop.name} ({anoop.email})")
print()

today = date.today()

# ── 1. Tickets ────────────────────────────────────────────────────────────────

TICKETS = [
    # Already in seed but backlog — skip if exists
    # New tickets with active statuses
    {
        "jira_key":    "SNOP-201",
        "summary":     "ERP REST integration — authentication layer",
        "issue_type":  "Story",
        "status":      "In Progress",
        "priority":    "High",
        "pod":         "SNOP",
        "story_points": 8,
        "client":      "JFL",
    },
    {
        "jira_key":    "SNOP-202",
        "summary":     "Supplier data import: CSV parser + validation",
        "issue_type":  "Task",
        "status":      "In Progress",
        "priority":    "Medium",
        "pod":         "SNOP",
        "story_points": 5,
        "client":      "JFL",
    },
    {
        "jira_key":    "SNOP-203",
        "summary":     "Stock level dashboard — real-time WebSocket feed",
        "issue_type":  "Story",
        "status":      "In Review",
        "priority":    "Medium",
        "pod":         "SNOP",
        "story_points": 5,
        "client":      "JFL",
    },
    {
        "jira_key":    "SNOP-204",
        "summary":     "Unit tests for ERP integration module",
        "issue_type":  "Task",
        "status":      "Done",
        "priority":    "Low",
        "pod":         "SNOP",
        "story_points": 3,
        "client":      "JFL",
    },
    {
        "jira_key":    "SNOP-205",
        "summary":     "Supplier onboarding flow — UI wireframes review",
        "issue_type":  "Task",
        "status":      "Done",
        "priority":    "Low",
        "pod":         "SNOP",
        "story_points": 2,
        "client":      "JFL",
    },
    {
        "jira_key":    "EDM-101",
        "summary":     "Data pipeline optimisation — reduce latency by 40%",
        "issue_type":  "Epic",
        "status":      "In Progress",
        "priority":    "High",
        "pod":         "EDM",
        "story_points": 13,
        "client":      "3SC",
    },
    {
        "jira_key":    "EDM-102",
        "summary":     "Implement retry logic for failed ETL jobs",
        "issue_type":  "Task",
        "status":      "In Review",
        "priority":    "High",
        "pod":         "EDM",
        "story_points": 3,
        "client":      "3SC",
    },
    {
        "jira_key":    "EDM-103",
        "summary":     "Schema migration: add audit columns to pipeline tables",
        "issue_type":  "Task",
        "status":      "Done",
        "priority":    "Medium",
        "pod":         "EDM",
        "story_points": 2,
        "client":      "3SC",
    },
]

ticket_ids = []
for t in TICKETS:
    exists = db.query(JiraTicket).filter(
        JiraTicket.org_id    == org.id,
        JiraTicket.jira_key  == t["jira_key"],
    ).first()
    if exists:
        print(f"  skip  {t['jira_key']} (already exists)")
        ticket_ids.append((exists.id, t["client"] or ""))
        continue

    ticket = JiraTicket(
        id              = gen_uuid(),
        org_id          = org.id,
        jira_key        = t["jira_key"],
        project_key     = t["jira_key"].split("-")[0],
        summary         = t["summary"],
        issue_type      = t["issue_type"],
        status          = t["status"],
        assignee        = anoop.name,
        assignee_email  = anoop.email,
        pod             = t["pod"],
        client          = t.get("client"),
        priority        = t["priority"],
        story_points    = t.get("story_points"),
        hours_spent     = 0,
        is_deleted      = False,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    ticket_ids.append((ticket.id, t.get("client", "")))
    print(f"  ✅  {t['jira_key']} — {t['summary'][:55]}")


# ── 2. Worklogs (current + previous month) ────────────────────────────────────

print()
print("Adding worklogs…")

# Helper: working days in a range
def working_days(start: date, end: date):
    d, days = start, []
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days

# This month
month_start = today.replace(day=1)
prev_month_end   = month_start - timedelta(days=1)
prev_month_start = prev_month_end.replace(day=1)

this_month_days = working_days(month_start, today)
prev_month_days = working_days(prev_month_start, prev_month_end)

import random
random.seed(42)

wl_count = 0
for ticket_id, client in ticket_ids[:5]:   # log hours on first 5 tickets
    # This month: 4–7 log entries
    for log_date in random.sample(this_month_days, min(5, len(this_month_days))):
        exists = db.query(Worklog).filter(
            Worklog.ticket_id  == ticket_id,
            Worklog.author     == anoop.name,
            Worklog.log_date   == log_date,
        ).first()
        if exists:
            continue
        wl = Worklog(
            id           = gen_uuid(),
            ticket_id    = ticket_id,
            author       = anoop.name,
            author_email = anoop.email,
            log_date     = log_date,
            hours        = round(random.uniform(2.0, 6.0) * 2) / 2,  # 2–6h in 0.5h steps
            comment      = "Progress update",
        )
        db.add(wl)
        wl_count += 1

    # Previous month: 3–5 log entries
    for log_date in random.sample(prev_month_days, min(4, len(prev_month_days))):
        exists = db.query(Worklog).filter(
            Worklog.ticket_id  == ticket_id,
            Worklog.author     == anoop.name,
            Worklog.log_date   == log_date,
        ).first()
        if exists:
            continue
        wl = Worklog(
            id           = gen_uuid(),
            ticket_id    = ticket_id,
            author       = anoop.name,
            author_email = anoop.email,
            log_date     = log_date,
            hours        = round(random.uniform(2.0, 5.0) * 2) / 2,
            comment      = "Development work",
        )
        db.add(wl)
        wl_count += 1

db.commit()
print(f"  ✅  {wl_count} worklogs added")


# ── 3. Manual entries ─────────────────────────────────────────────────────────

print()
print("Adding manual entries…")

MANUAL = [
    {
        "entry_date": today - timedelta(days=1),
        "activity":   "Sprint planning — SNOP ERP integration scope review",
        "hours":      2.0,
        "pod":        "SNOP",
        "client":     "JFL",
        "entry_type": "Meeting",
    },
    {
        "entry_date": today - timedelta(days=3),
        "activity":   "Backlog grooming session with product owner",
        "hours":      1.5,
        "pod":        "SNOP",
        "client":     "JFL",
        "entry_type": "Meeting",
    },
    {
        "entry_date": today - timedelta(days=5),
        "activity":   "EDM pipeline performance analysis and documentation",
        "hours":      3.0,
        "pod":        "EDM",
        "client":     "3SC",
        "entry_type": "Feature",
    },
    {
        "entry_date": prev_month_end - timedelta(days=2),
        "activity":   "Code review — supplier data import module",
        "hours":      1.5,
        "pod":        "SNOP",
        "client":     "JFL",
        "entry_type": "Bugs",
    },
    {
        "entry_date": prev_month_end - timedelta(days=7),
        "activity":   "Program management — Q2 delivery roadmap update",
        "hours":      2.0,
        "pod":        "SNOP",
        "client":     "JFL",
        "entry_type": "Program Management",
    },
]

me_count = 0
for m in MANUAL:
    exists = db.query(ManualEntry).filter(
        ManualEntry.user_id    == anoop.id,
        ManualEntry.entry_date == m["entry_date"],
        ManualEntry.activity   == m["activity"],
    ).first()
    if exists:
        print(f"  skip  manual entry on {m['entry_date']} (already exists)")
        continue

    entry = ManualEntry(
        id         = gen_uuid(),
        user_id    = anoop.id,
        org_id     = org.id,
        entry_date = m["entry_date"],
        activity   = m["activity"],
        hours      = m["hours"],
        pod        = m["pod"],
        client     = m["client"],
        entry_type = m["entry_type"],
        status     = "confirmed",
        ai_parsed  = False,
    )
    db.add(entry)
    me_count += 1

db.commit()
print(f"  ✅  {me_count} manual entries added")

db.close()
print()
print("🎉 Done! Anoop Kumar Rai now has:")
print(f"   • {len(TICKETS)} tickets (In Progress / In Review / Done)")
print(f"   • {wl_count} worklogs (this + last month)")
print(f"   • {me_count} manual entries")
print()
print("Run the backend and reload the dashboard to see the data.")
