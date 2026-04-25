"""
app/ai/documents.py — NOVA document generation.

Functions:
  generate_sprint_retro   — structured retro markdown from Done tickets
  generate_release_notes  — grouped changelog from Done tickets
  extract_action_items    — action items from raw meeting notes
  generate_standup        — Yesterday/Today/Blockers for a user
"""

import json
import logging
from datetime import date, timedelta

from app.ai.nova import chat

logger = logging.getLogger(__name__)


async def generate_sprint_retro(sprint_id: str, org_id: str, db) -> str:
    """Generate a structured sprint retrospective from Done tickets."""
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket

    sprint = db.query(Sprint).filter(Sprint.id == sprint_id, Sprint.org_id == org_id).first()
    if not sprint:
        return "Sprint not found."

    tickets = db.query(JiraTicket).filter(
        JiraTicket.sprint_id == sprint_id,
        JiraTicket.is_deleted == False,
    ).all()

    done      = [t for t in tickets if t.status == "Done"]
    not_done  = [t for t in tickets if t.status != "Done"]
    total_pts = sum(t.story_points or 0 for t in done)

    ticket_summary = "\n".join(
        f"- [{t.issue_type}] {t.jira_key}: {t.summary} ({t.story_points or 0} pts, {t.assignee or 'unassigned'})"
        for t in done
    )
    incomplete = "\n".join(f"- {t.jira_key}: {t.summary}" for t in not_done)

    prompt = f"""Generate a sprint retrospective for sprint "{sprint.name}".

Sprint goal: {sprint.goal or 'Not set'}
Completed: {len(done)}/{len(tickets)} tickets ({total_pts} story points)
Date range: {sprint.start_date} → {sprint.end_date}

Completed tickets:
{ticket_summary or 'None'}

Incomplete tickets:
{incomplete or 'None'}

Write a retrospective with these sections in markdown:
## Sprint Summary
## What Went Well ✅
## What Could Be Improved 🔧
## Action Items 📋
## Metrics

Be specific, reference actual ticket names."""

    return await chat(prompt, temperature=0, max_tokens=1200)


async def generate_release_notes(sprint_id: str, org_id: str, db) -> str:
    """Generate release notes / changelog from Done tickets in a sprint."""
    from app.models.sprint import Sprint
    from app.models.ticket import JiraTicket

    sprint = db.query(Sprint).filter(Sprint.id == sprint_id, Sprint.org_id == org_id).first()
    if not sprint:
        return "Sprint not found."

    done_tickets = db.query(JiraTicket).filter(
        JiraTicket.sprint_id == sprint_id,
        JiraTicket.status    == "Done",
        JiraTicket.is_deleted == False,
    ).all()

    by_type: dict = {}
    for t in done_tickets:
        key = t.issue_type or "Task"
        by_type.setdefault(key, []).append(t)

    sections = []
    for itype, items in by_type.items():
        lines = "\n".join(f"  - {t.jira_key}: {t.summary}" for t in items)
        sections.append(f"**{itype}s:**\n{lines}")

    grouped = "\n\n".join(sections) or "No completed tickets."

    prompt = f"""Generate release notes for sprint "{sprint.name}".

Completed work:
{grouped}

Write clean, user-facing release notes in markdown:
## Release Notes — {sprint.name}
### New Features
### Bug Fixes
### Improvements
### Technical Changes

Use bullet points. Keep language clear for both technical and non-technical readers."""

    return await chat(prompt, temperature=0, max_tokens=800)


async def extract_action_items(meeting_notes: str) -> list[dict]:
    """Extract structured action items from raw meeting notes."""
    prompt = f"""Extract action items from these meeting notes.
Return ONLY valid JSON — no other text.

Meeting notes:
{meeting_notes}

Return:
{{
  "action_items": [
    {{
      "action": "what needs to be done",
      "owner": "person responsible or null",
      "due": "YYYY-MM-DD or null",
      "priority": "High|Medium|Low"
    }}
  ]
}}"""
    try:
        raw   = await chat(prompt, temperature=0, max_tokens=600)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        return json.loads(raw[start:end]).get("action_items", [])
    except Exception as e:
        logger.warning(f"extract_action_items failed: {e}")
        return []


async def generate_standup(user_id: str, org_id: str, standup_date: str, db) -> dict:
    """Generate Yesterday/Today/Blockers standup for a user from their worklogs."""
    from app.models.user import User
    from app.models.ticket import JiraTicket, Worklog
    from app.models.sprint import Standup
    from app.models.base import gen_uuid

    user = db.query(User).filter(User.id == user_id, User.org_id == org_id).first()
    if not user:
        return {"error": "User not found"}

    today_dt     = date.fromisoformat(standup_date)
    yesterday_dt = today_dt - timedelta(days=1)
    # Skip weekends
    if yesterday_dt.weekday() >= 5:
        yesterday_dt -= timedelta(days=yesterday_dt.weekday() - 4)

    # Yesterday's worklogs joined with their ticket for the ticket key + summary
    yesterday_logs = (
        db.query(Worklog, JiraTicket)
        .join(JiraTicket, Worklog.ticket_id == JiraTicket.id)
        .filter(
            Worklog.author_email == user.email,
            Worklog.log_date     == yesterday_dt,
        )
        .all()
    )

    # Recently completed tickets assigned to the user (Done/Closed in last 3 days)
    recent_cutoff = today_dt - timedelta(days=3)
    completed_tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id     == org_id,
        JiraTicket.assignee   == user.name,
        JiraTicket.status.in_(["Done", "Closed", "Resolved"]),
        JiraTicket.is_deleted   == False,
        JiraTicket.jira_updated >= recent_cutoff,
    ).order_by(JiraTicket.jira_updated.desc()).limit(5).all()

    # Today's in-progress tickets (assigned to user)
    today_tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id        == org_id,
        JiraTicket.assignee      == user.name,
        JiraTicket.status.in_(["In Progress", "In Review"]),
        JiraTicket.is_deleted    == False,
    ).limit(5).all()

    # Build yesterday summary — prefer ticket keys from worklogs + completed tickets
    seen_keys: set = set()
    yesterday_lines = []
    for wl, ticket in yesterday_logs:
        if ticket.jira_key not in seen_keys:
            seen_keys.add(ticket.jira_key)
            action = "Worked on" if ticket.status not in ("Done", "Closed", "Resolved") else "Completed"
            yesterday_lines.append(f"- {action} {ticket.jira_key}: {ticket.summary} ({wl.hours}h)")
    for t in completed_tickets:
        if t.jira_key not in seen_keys:
            seen_keys.add(t.jira_key)
            yesterday_lines.append(f"- Completed {t.jira_key}: {t.summary}")
    yesterday_summary = "\n".join(yesterday_lines) or "No logged work found for yesterday."

    today_summary = "\n".join(
        f"- {t.jira_key}: {t.summary}" for t in today_tickets
    ) or "No active tickets assigned."

    prompt = f"""Generate a daily standup for {user.name} ({user.role}, {user.pod or 'no pod'}).

Yesterday's completed/in-progress work (use these EXACT ticket keys in your output):
{yesterday_summary}

Today's active tickets (use these EXACT ticket keys):
{today_summary}

Write a natural, first-person standup update. Reference ticket keys (e.g. "Completed TRKLY-4 — fixed login screen").
**Yesterday:** (what they did, with ticket keys)
**Today:** (what they plan to do, with ticket keys)
**Blockers:** (any blockers or 'None')

Be concise — 2-3 bullet points per section max."""

    try:
        raw_text = await chat(prompt, temperature=0, max_tokens=400)
    except Exception as e:
        logger.warning(f"NOVA standup generation failed: {e}")
        raw_text = f"Yesterday: {yesterday_summary}\nToday: {today_summary}\nBlockers: None"

    # Parse sections
    def _extract(text: str, key: str) -> str:
        import re
        m = re.search(rf"\*\*{key}[:\*]*\*?\s*(.*?)(?=\*\*|\Z)", text, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else ""

    yesterday_out = _extract(raw_text, "Yesterday")
    today_out     = _extract(raw_text, "Today")
    blockers_out  = _extract(raw_text, "Blockers")

    # Upsert into standups table
    existing = db.query(Standup).filter(
        Standup.user_id == user_id,
        Standup.date    == today_dt,
    ).first()

    if existing:
        existing.yesterday = yesterday_out
        existing.today     = today_out
        existing.blockers  = blockers_out
        standup = existing
    else:
        standup = Standup(
            id=gen_uuid(), user_id=user_id, org_id=org_id,
            date=today_dt,
            yesterday=yesterday_out, today=today_out, blockers=blockers_out,
        )
        db.add(standup)
    db.commit()
    db.refresh(standup)

    return {
        "id":             standup.id,
        "user_id":        standup.user_id,
        "engineer":       user.name,
        "engineer_email": user.email,
        "pod":            user.pod or "",
        "date":           standup.date.isoformat(),
        "yesterday":      standup.yesterday,
        "today":          standup.today,
        "blockers":       standup.blockers or "",
        "shared":         standup.is_shared,
        "created_at":     standup.date.isoformat(),
    }
