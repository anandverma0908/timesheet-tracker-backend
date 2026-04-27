"""
app/api/routes/manual_entries.py — Time entry endpoints.

POST /api/ai/parse-entries   AI parse of natural language time text → structured entries
POST /api/manual-entries     Save confirmed entries to the database
GET  /api/activity           Combined activity feed (worklogs + manual entries) for calendar
"""
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["manual-entries"])

# Map frontend entry types → valid DB enum values (avoids needing a migration)
_TYPE_MAP = {
    "Meeting":           "Meeting",
    "Bugs":              "Bugs",
    "Feature":           "Feature",
    "Program Management":"Program Management",
    "1:1":               "Meeting",
    "Planning":          "Meeting",
    "Review":            "Feature",
    "Interview":         "Meeting",
    "Reporting":         "Feature",
    "Training":          "Meeting",
}


# ── Schemas ────────────────────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    text: str
    pods: list[str] = []
    clients: list[str] = []


class EntryIn(BaseModel):
    entry_date: str
    activity: str
    hours: float
    pod: Optional[str] = None
    client: Optional[str] = None
    entry_type: str = "Meeting"
    notes: Optional[str] = None
    ai_parsed: bool = True


class BulkEntryRequest(BaseModel):
    ai_raw_input: Optional[str] = None
    entries: list[EntryIn]


# ── POST /api/ai/parse-entries ─────────────────────────────────────────────────

@router.post("/ai/parse-entries")
async def parse_entries(
    body: ParseRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Use NOVA to parse natural language time text into structured entries.
    Example input: "sprint planning 2h DPAI, 1:1s with team 1h, bug fixes 3h"
    """
    from app.ai.nova import chat

    today = date.today().isoformat()
    pods_str    = ", ".join(body.pods)    if body.pods    else "none configured"
    clients_str = ", ".join(body.clients) if body.clients else "none configured"

    prompt = f"""Parse the following work log text into structured time entries.

Text: "{body.text}"

Today's date: {today}
Available PODs: {pods_str}
Available clients: {clients_str}

Return ONLY a valid JSON object — no prose, no markdown fences.

{{
  "entries": [
    {{
      "date": "YYYY-MM-DD",
      "activity": "short description of the work",
      "hours": 2.0,
      "pod": "matched POD name or null",
      "client": "matched client name or null",
      "type": "Meeting|Bugs|Feature|Program Management|1:1|Planning|Review|Interview|Reporting|Training",
      "notes": "",
      "confidence": "high|medium|low"
    }}
  ],
  "warnings": []
}}

Rules:
- Use today's date ({today}) unless the text mentions a specific date or day
- Match POD names from the available list (case-insensitive, partial match OK)
- Match client names from the available list (case-insensitive, partial match OK)
- Hours can be decimal: 1.5 for 1h30m, 0.5 for 30min, 0.25 for 15min
- Infer type from the activity: standups/meetings/calls → Meeting, code/bugs/fixes → Bugs, features/build → Feature, 1:1 → 1:1, planning/grooming → Planning, PR review/code review → Review, interview → Interview, report/reporting → Reporting, training/learning → Training
- Split comma-separated or newline-separated activities into separate entries
- Add a warning string for anything ambiguous"""

    try:
        raw = await chat(user_message=prompt, temperature=0.1, max_tokens=1500)

        import json, re
        cleaned = raw.strip()
        if "```" in cleaned:
            cleaned = re.sub(r"```[a-z]*\n?", "", cleaned).strip()

        # Extract JSON object
        start = cleaned.find("{")
        end   = cleaned.rfind("}")
        if start != -1 and end > start:
            cleaned = cleaned[start: end + 1]

        data = json.loads(cleaned)
        return {
            "entries":  data.get("entries",  []),
            "warnings": data.get("warnings", []),
        }

    except Exception as exc:
        logger.error("AI parse-entries failed: %s", exc)
        # Return empty so frontend falls back to local parser
        raise


# ── POST /api/manual-entries ───────────────────────────────────────────────────

@router.post("/manual-entries")
async def create_manual_entries(
    body: BulkEntryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save a batch of confirmed manual time entries for the current user."""
    from app.models.manual_entry import ManualEntry

    saved = []
    for e in body.entries:
        if not e.activity.strip() or e.hours <= 0:
            continue

        entry = ManualEntry(
            user_id      = current_user.id,
            org_id       = current_user.org_id,
            entry_date   = date.fromisoformat(e.entry_date),
            activity     = e.activity.strip(),
            hours        = e.hours,
            pod          = e.pod or None,
            client       = e.client or None,
            entry_type   = _TYPE_MAP.get(e.entry_type, "Meeting"),
            notes        = e.notes or None,
            ai_raw_input = body.ai_raw_input,
            ai_parsed    = e.ai_parsed,
            status       = "confirmed",
        )
        db.add(entry)
        db.flush()
        saved.append(entry)

    db.commit()
    for e in saved:
        db.refresh(e)

    return [
        {
            "id":         str(e.id),
            "entry_date": e.entry_date.isoformat(),
            "activity":   e.activity,
            "hours":      e.hours,
            "pod":        e.pod,
            "client":     e.client,
            "entry_type": e.entry_type,
            "notes":      e.notes,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in saved
    ]


# ── GET /api/activity ──────────────────────────────────────────────────────────

@router.get("/activity")
async def get_activity(
    date_from: str = Query(...),
    date_to:   str = Query(...),
    user:      Optional[str] = Query(None),   # manager viewing a team member
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Combined activity feed for the timesheet calendar.
    Returns both ticket worklogs and manual entries merged and sorted by date.
    When 'user' param is absent, returns the current user's own entries.
    """
    from app.models.ticket import JiraTicket, Worklog
    from app.models.manual_entry import ManualEntry
    from app.models.user import User as UserModel

    df = date.fromisoformat(date_from)
    dt = date.fromisoformat(date_to)

    # Determine whose data to return
    is_manager = current_user.role in ("admin", "engineering_manager")
    if user and is_manager:
        target_user = db.query(UserModel).filter(
            UserModel.org_id == current_user.org_id,
            UserModel.name == user,
        ).first()
        target_id = target_user.id if target_user else current_user.id
    else:
        target_id = current_user.id

    items = []

    # ── 1. Ticket worklogs ────────────────────────────────────────────────────
    worklogs = (
        db.query(Worklog, JiraTicket)
        .join(JiraTicket, Worklog.ticket_id == JiraTicket.id)
        .filter(
            Worklog.user_id   == target_id,
            Worklog.log_date  >= df,
            Worklog.log_date  <= dt,
            JiraTicket.is_deleted == False,
        )
        .all()
    )

    for wl, ticket in worklogs:
        items.append({
            "id":         str(wl.id),
            "source":     "ticket",
            "date":       wl.log_date.isoformat(),
            "activity":   wl.comment or ticket.summary or "",
            "hours":      float(wl.hours or 0),
            "pod":        ticket.pod if hasattr(ticket, "pod") else None,
            "client":     ticket.client if hasattr(ticket, "client") else None,
            "entry_type": ticket.issue_type if hasattr(ticket, "issue_type") else None,
            "ticket_key": ticket.key,
            "notes":      wl.comment or None,
            "user_name":  wl.author or current_user.name,
        })

    # ── 2. Manual entries ─────────────────────────────────────────────────────
    manual = (
        db.query(ManualEntry)
        .filter(
            ManualEntry.user_id    == target_id,
            ManualEntry.entry_date >= df,
            ManualEntry.entry_date <= dt,
        )
        .all()
    )

    for me in manual:
        items.append({
            "id":         str(me.id),
            "source":     "manual",
            "date":       me.entry_date.isoformat(),
            "activity":   me.activity,
            "hours":      float(me.hours or 0),
            "pod":        me.pod,
            "client":     me.client,
            "entry_type": me.entry_type,
            "ticket_key": None,
            "notes":      me.notes,
            "user_name":  current_user.name,
        })

    items.sort(key=lambda x: x["date"])
    return items
