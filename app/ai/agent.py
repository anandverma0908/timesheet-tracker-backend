"""
NOVA Agent — autonomous multi-step task execution engine.

Implements a tool-calling agent loop:
  while iteration < MAX:
    → call LLM with current context
    → if JSON tool call → execute → append result → continue
    → if plain text    → final answer, break

Public entry point: run_agent_loop()
"""
import json
import logging
import re
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.ai.nova import chat
from app.models.user import User

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 8

# ── Conversational bypass ─────────────────────────────────────────────────────
# Messages that match this pattern don't need the agent loop at all.
_CONVO_RE = re.compile(
    r"^\s*("
    r"hi|hello|hey|howdy|sup|yo|hiya|greetings|"
    r"good\s*(morning|afternoon|evening|day|night)|"
    r"thanks|thank\s*(you|u)|thx|ty|cheers|"
    r"bye|goodbye|see\s*ya?|"
    r"ok(ay)?|cool|great|awesome|nice|got\s*it|"
    r"what\s*can\s*you\s*do|help|who\s*are\s*you|what\s*are\s*you"
    r")\s*[!?.]*\s*$",
    re.IGNORECASE,
)

def _is_conversational(message: str) -> bool:
    """True when the message is a greeting/small-talk that needs no tools."""
    stripped = message.strip()
    return bool(_CONVO_RE.match(stripped)) or len(stripped.split()) <= 2


_CONVO_SYSTEM = (
    "You are NOVA/EOS — the intelligent AI operating system of Trackly. "
    "You are calm, precise, and slightly futuristic — think JARVIS. "
    "Reply naturally and concisely. Proactively suggest next actions when useful."
)


# ── System prompt ─────────────────────────────────────────────────────────────

VALID_STATUSES = ["Backlog", "To Do", "In Progress", "In Review", "Done", "Blocked"]

# Fuzzy aliases users commonly say → canonical status
_STATUS_ALIASES: dict[str, str] = {
    "blocker":      "Blocked",
    "blocked":      "Blocked",
    "block":        "Blocked",
    "blocking":     "Blocked",
    "todo":         "To Do",
    "to-do":        "To Do",
    "backlog":      "Backlog",
    "in progress":  "In Progress",
    "inprogress":   "In Progress",
    "wip":          "In Progress",
    "in review":    "In Review",
    "inreview":     "In Review",
    "review":       "In Review",
    "done":         "Done",
    "complete":     "Done",
    "completed":    "Done",
    "closed":       "Done",
    "resolved":     "Done",
}

def _normalize_status(raw: str) -> str:
    """Map user-facing status aliases to the canonical stored value."""
    return _STATUS_ALIASES.get(raw.strip().lower(), raw.strip())


AGENT_SYSTEM_PROMPT = """You are EOS — the intelligent AI operating system of the Trackly platform. You are concise, precise, slightly futuristic, and warm. Think JARVIS but female. Never verbose.

=== HOW TO RESPOND ===

You respond in one of two ways ONLY. Pick one. Never mix them.

[1] CALL A TOOL — output exactly this JSON and nothing else:
{{"action": "tool_name", "parameters": {{"key": "value"}}, "reasoning": "brief why"}}

[2] GIVE YOUR ANSWER — output plain text (markdown allowed). No JSON. No labels. Just the answer.

Do NOT start your response with any label like "MODE", "Status", "FINAL ANSWER" etc. Just output the JSON or the answer directly.

=== STRICT RULES ===

1. NEVER guess, fabricate, or invent ticket keys, names, or data. If you have not called a tool yet, you do not know the answer.
2. ALWAYS call a tool first when the user asks about tickets, sprints, blockers, decisions, wiki, standup, or timesheet.
3. Once you have tool results in context, write your answer immediately. Do not call the same tool again.
4. For greetings or small talk only, reply directly without tools.

=== TOOLS ===

search — Search tickets, wiki, decisions, standups across ALL pods/spaces.
  Parameters: query (string), scope ("all" | "tickets" | "wiki", default "all")
  Use for: any question about open tickets, blockers, bugs, sprint status, team work

get_ticket — Fetch one ticket by exact key.
  Parameters: key (string)  e.g. "TRKLY-1"

update_ticket_status — Change a ticket's status.
  Parameters: key (string), status ("Backlog" | "To Do" | "In Progress" | "In Review" | "Done" | "Blocked")

rag_query — Ask a natural-language question against the full knowledge index.
  Parameters: question (string)
  Use for: summaries, synthesis, "what did we decide about X"

get_timesheet — Fetch the current user's timesheet (worklogs + manual entries).
  Parameters: days (int, default 14) — how many past calendar days to look back
  Use for: ANY question about time logged, hours, timesheet, missing days, daily hours
  Returns: per-day breakdown, total hours, list of days with no time logged

create_ticket — Create a new ticket. Only when user explicitly asks.
  Parameters: title (string), description (string), priority (string), issue_type (string)

create_wiki_page — Create a wiki page. Only when explicitly asked.
  Parameters: space_id (string), title (string), content (string)

generate_standup — Generate today's standup from recent activity.
  Parameters: (none)

=== EXAMPLES ===

User: "what tickets are open right now?"
Your response: {{"action": "search", "parameters": {{"query": "open", "scope": "tickets"}}, "reasoning": "search all tickets"}}

User: "how many days have I not logged time?"
Your response: {{"action": "get_timesheet", "parameters": {{"days": 14}}, "reasoning": "fetch timesheet to find unlogged days"}}

User: "show me my timesheet last week"
Your response: {{"action": "get_timesheet", "parameters": {{"days": 7}}, "reasoning": "fetch last 7 days of timesheet"}}

User: "what is TRKLY-5?"
Your response: {{"action": "get_ticket", "parameters": {{"key": "TRKLY-5"}}, "reasoning": "fetch ticket by key"}}

User: "hi"
Your response: Hey! What would you like to know about your project?

Limit: {max_iter} tool calls maximum."""


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_iteration_prompt(
    user_message: str,
    history: list[dict],
    steps: list[dict],
) -> str:
    parts = [f"USER REQUEST: {user_message}"]

    if history:
        parts.append("\nRECENT CONVERSATION:")
        for h in history[-6:]:
            role    = str(h.get("role", "user")).upper()
            content = str(h.get("content", ""))[:600]
            parts.append(f"[{role}] {content}")

    successful_tools: set[str] = set()
    if steps:
        parts.append("\nACTIONS TAKEN SO FAR:")
        for i, s in enumerate(steps):
            tc = s.get("tool_call")
            if not tc:
                continue
            tr = s.get("tool_result", {})
            if tr.get("success"):
                result_str = json.dumps(tr.get("data", ""))[:800]
                successful_tools.add(tc["action"])
            else:
                result_str = f"ERROR: {tr.get('error', 'unknown error')}"
            params_str = json.dumps(tc.get("parameters", {}))[:200]
            parts.append(
                f"Step {i + 1}: called {tc['action']}({params_str})\n"
                f"  Result: {result_str}"
            )

        if successful_tools:
            parts.append(
                "\n⚠️  YOU ALREADY HAVE DATA FROM: "
                + ", ".join(successful_tools)
                + ".\nDo NOT call any of these tools again. "
                  "Write your FINAL ANSWER now as plain text. No JSON. No tool calls."
            )
        else:
            parts.append(
                "\nContinue: either call the next tool OR provide your final plain-text answer."
            )

    return "\n".join(parts)


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_tool_call(text: str) -> Optional[dict]:
    """
    Detect a JSON tool call in raw LLM output.
    Returns the parsed dict only when the response is predominantly a tool call
    (JSON is found and there is no substantial prose wrapping it).
    Returns None for plain-text final answers or mixed responses.
    """
    text = text.strip()

    # 1. Fenced JSON block (```json ... ```)
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj.get("action"), str) and obj["action"]:
                # Reject if substantial prose surrounds the block
                prose = text[:m.start()].strip() + text[m.end():].strip()
                if len(prose) > 120:
                    return None
                return obj
        except json.JSONDecodeError:
            pass

    # 2. Bare JSON object starting with { containing "action"
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end <= start:
        return None

    # Only parse if the JSON is the bulk of the response.
    # Allow up to 80 chars of prose before the JSON (model might emit a short prefix).
    # But reject if there's a full sentence of prose AND more prose after the JSON.
    prose_before = text[:start].strip()
    prose_after  = text[end + 1:].strip()

    if len(prose_before) > 80:
        return None

    # If there's significant prose after the JSON it's a mixed response — reject
    if len(prose_after) > 60:
        return None

    try:
        obj = json.loads(text[start:end + 1])
        if isinstance(obj.get("action"), str) and obj["action"]:
            return obj
    except json.JSONDecodeError:
        pass

    return None


# ── Tool handlers ─────────────────────────────────────────────────────────────

async def _tool_get_ticket(params: dict, user: User, db: Session) -> dict:
    from app.models.ticket import JiraTicket

    key = str(params.get("key", "")).strip().upper()
    if not key:
        return {"error": "key parameter is required"}

    ticket = db.query(JiraTicket).filter(
        JiraTicket.jira_key == key,
        JiraTicket.org_id   == user.org_id,
        JiraTicket.is_deleted == False,
    ).first()

    if not ticket:
        return {"error": f"Ticket {key} not found"}

    return {
        "key":         ticket.jira_key,
        "title":       ticket.summary,
        "status":      ticket.status,
        "priority":    ticket.priority,
        "issue_type":  ticket.issue_type,
        "assignee":    ticket.assignee,
        "description": (ticket.description or "")[:300],
        "pod":         ticket.pod,
    }


async def _tool_update_ticket_status(params: dict, user: User, db: Session) -> dict:
    from app.models.ticket import JiraTicket
    from app.models.audit import AuditLog

    key        = str(params.get("key", "")).strip().upper()
    raw_status = str(params.get("status", "")).strip()
    status     = _normalize_status(raw_status)

    if not key:
        return {"error": "key parameter is required"}
    if not status:
        return {"error": "status parameter is required"}
    if status not in VALID_STATUSES:
        return {
            "error": f'"{status}" is not a valid status. '
                     f"Valid values: {', '.join(VALID_STATUSES)}"
        }

    ticket = db.query(JiraTicket).filter(
        JiraTicket.jira_key   == key,
        JiraTicket.org_id     == user.org_id,
        JiraTicket.is_deleted == False,
    ).first()

    if not ticket:
        return {"error": f"Ticket {key} not found"}

    old_status    = ticket.status
    ticket.status = status

    # Write audit log using same pattern as the tickets route
    from app.models.base import gen_uuid
    db.add(AuditLog(
        id=gen_uuid(),
        entity_type="ticket",
        entity_id=str(ticket.id),
        org_id=user.org_id,
        user_id=str(user.id),
        action="status_changed",
        diff_json={"old": old_status, "new": status},
    ))
    db.commit()
    db.refresh(ticket)

    logger.info(f"Agent updated {key} status: {old_status!r} → {status!r} (user {user.id})")
    return {
        "key":        key,
        "old_status": old_status,
        "new_status": status,
        "updated":    True,
    }


async def _tool_search(params: dict, user: User, db: Session) -> dict:
    from app.ai.search import semantic_search, keyword_search_tickets

    query = str(params.get("query", "")).strip()
    scope = str(params.get("scope", "all"))
    if not query:
        return {"error": "query parameter is required"}

    results = []
    if scope in ("all", "tickets"):
        kw = await keyword_search_tickets(query, user.org_id)
        results.extend(kw)
    if scope in ("all", "wiki"):
        sem = await semantic_search(query, user.org_id, limit=8)
        results.extend(sem)

    # Deduplicate by key/id
    seen, deduped = set(), []
    for r in results:
        key = str(r.get("id") or r.get("key") or r.get("title", ""))
        if key not in seen:
            seen.add(key)
            deduped.append({
                "key":     r.get("key") or r.get("jira_key"),
                "title":   r.get("title") or r.get("summary"),
                "type":    r.get("type", "ticket"),
                "status":  r.get("status"),
                "snippet": (r.get("snippet") or r.get("description") or "")[:200],
            })

    return {"results": deduped[:6], "count": len(deduped)}


async def _tool_rag_query(params: dict, user: User, db: Session) -> dict:
    from app.ai.search import nl_query

    question = str(params.get("question", "")).strip()
    if not question:
        return {"error": "question parameter is required"}

    data = await nl_query(question, user.org_id)
    return {
        "answer": data.get("answer", ""),
        "citations": [
            {
                "key":   s.get("key"),
                "title": s.get("title"),
                "type":  s.get("type"),
            }
            for s in data.get("sources", [])[:5]
        ],
    }


async def _tool_create_ticket(params: dict, user: User, db: Session) -> dict:
    from app.models.ticket import JiraTicket
    from app.models.base import gen_uuid
    import sqlalchemy

    title       = str(params.get("title", "")).strip()
    description = str(params.get("description", "")).strip()
    if not title:
        return {"error": "title parameter is required"}

    # Generate next jira key
    count = db.execute(
        sqlalchemy.text("SELECT COUNT(*) FROM jira_tickets WHERE org_id = :oid"),
        {"oid": user.org_id},
    ).scalar() or 0
    jira_key = f"TRKLY-{count + 1}"

    ticket = JiraTicket(
        id=gen_uuid(),
        org_id=user.org_id,
        jira_key=jira_key,
        project_key=jira_key.split("-")[0],
        summary=title,
        description=description or None,
        issue_type=str(params.get("issue_type", "Task")),
        priority=str(params.get("priority", "Medium")),
        status="To Do",
        reporter=user.name,
        labels=[],
        is_deleted=False,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    logger.info(f"Agent created ticket {jira_key} for user {user.id}")
    return {
        "key":        jira_key,
        "id":         str(ticket.id),
        "title":      title,
        "priority":   ticket.priority,
        "issue_type": ticket.issue_type,
        "status":     "created",
    }


async def _tool_create_wiki_page(params: dict, user: User, db: Session) -> dict:
    from app.models.wiki import WikiPage
    from app.models.base import gen_uuid

    space_id = str(params.get("space_id", "")).strip()
    title    = str(params.get("title", "")).strip()
    content  = str(params.get("content", "")).strip()

    if not space_id:
        return {"error": "space_id is required"}
    if not title:
        return {"error": "title is required"}
    if not content:
        return {"error": "content is required"}

    page = WikiPage(
        id=gen_uuid(),
        org_id=user.org_id,
        space_id=space_id,
        parent_id=params.get("parent_id") or None,
        title=title,
        content_md=content,
        version=1,
        author_id=str(user.id),
        author_name=user.name,
        is_deleted=False,
    )
    db.add(page)
    db.commit()
    db.refresh(page)

    logger.info(f"Agent created wiki page '{title}' (id={page.id}) for user {user.id}")
    return {
        "id":       str(page.id),
        "title":    title,
        "space_id": space_id,
        "status":   "created",
    }


async def _tool_get_timesheet(params: dict, user: User, db: Session) -> dict:
    from datetime import timedelta
    from app.models.ticket import Worklog, JiraTicket
    from app.models.manual_entry import ManualEntry

    days = max(1, min(int(params.get("days", 14)), 60))
    today = date.today()
    date_from = today - timedelta(days=days - 1)

    # ── 1. Ticket worklogs ────────────────────────────────────────────────────
    worklogs = (
        db.query(Worklog, JiraTicket)
        .join(JiraTicket, Worklog.ticket_id == JiraTicket.id)
        .filter(
            Worklog.author_email == user.email,
            Worklog.log_date >= date_from,
            Worklog.log_date <= today,
            JiraTicket.is_deleted == False,
        )
        .all()
    )

    # ── 2. Manual entries ─────────────────────────────────────────────────────
    manual = (
        db.query(ManualEntry)
        .filter(
            ManualEntry.user_id == user.id,
            ManualEntry.entry_date >= date_from,
            ManualEntry.entry_date <= today,
        )
        .all()
    )

    # Build per-day buckets (only weekdays)
    all_weekdays = []
    d = date_from
    while d <= today:
        if d.weekday() < 5:  # Mon–Fri
            all_weekdays.append(d)
        d += timedelta(days=1)

    hours_by_day: dict[str, float] = {d.isoformat(): 0.0 for d in all_weekdays}
    entries_by_day: dict[str, list] = {d.isoformat(): [] for d in all_weekdays}

    for wl, ticket in worklogs:
        k = wl.log_date.isoformat()
        if k in hours_by_day:
            hours_by_day[k] += float(wl.hours or 0)
            entries_by_day[k].append({"activity": ticket.summary, "hours": float(wl.hours or 0), "source": "ticket"})

    for me in manual:
        k = me.entry_date.isoformat()
        if k in hours_by_day:
            hours_by_day[k] += float(me.hours or 0)
            entries_by_day[k].append({"activity": me.activity, "hours": float(me.hours or 0), "source": "manual"})

    unlogged_days = [d for d, h in hours_by_day.items() if h == 0]
    low_days = [d for d, h in hours_by_day.items() if 0 < h < 4]
    total_hours = sum(hours_by_day.values())

    day_summary = [
        {"date": d, "hours": round(hours_by_day[d], 2), "entries": entries_by_day[d]}
        for d in sorted(hours_by_day.keys())
    ]

    return {
        "period": f"{date_from.isoformat()} to {today.isoformat()}",
        "working_days": len(all_weekdays),
        "total_hours": round(total_hours, 2),
        "avg_hours_per_day": round(total_hours / max(1, len(all_weekdays)), 2),
        "unlogged_days": unlogged_days,
        "unlogged_count": len(unlogged_days),
        "low_hours_days": low_days,
        "days": day_summary,
    }


async def _tool_generate_standup(params: dict, user: User, db: Session) -> dict:
    from app.ai.documents import generate_standup

    result = await generate_standup(
        str(user.id),
        user.org_id,
        date.today().isoformat(),
        db,
    )
    return {"standup": result, "status": "generated"}


# ── Tool registry ─���───────────────────────────────────────────────────────────

_TOOL_HANDLERS = {
    "get_ticket":            _tool_get_ticket,
    "update_ticket_status":  _tool_update_ticket_status,
    "search":                _tool_search,
    "rag_query":             _tool_rag_query,
    "get_timesheet":         _tool_get_timesheet,
    "create_ticket":         _tool_create_ticket,
    "create_wiki_page":      _tool_create_wiki_page,
    "generate_standup":      _tool_generate_standup,
}


async def _execute_tool(action: str, params: dict, user: User, db: Session) -> dict:
    handler = _TOOL_HANDLERS.get(action)
    if not handler:
        known = ", ".join(_TOOL_HANDLERS.keys())
        return {
            "success": False,
            "data":    None,
            "error":   f'Unknown tool "{action}". Available: {known}',
        }
    try:
        data = await handler(params, user, db)
        return {"success": True, "data": data}
    except Exception as exc:
        logger.exception(f"Tool '{action}' raised an exception")
        return {"success": False, "data": None, "error": str(exc)}


# ── Public entry point ────────────────────────────────────────────────────────

async def run_agent_loop(
    user_message: str,
    user: User,
    db: Session,
    history: Optional[list[dict]] = None,
    max_iterations: int = MAX_ITERATIONS,
) -> dict:
    """
    Run the NOVA agent loop for a single user message.

    Returns:
        answer         — final plain-text answer from the agent
        steps          — list of {iteration, tool_call, tool_result, timestamp}
        tools_used     — names of all tools called in order
        created_ticket — {id, title, priority, issue_type} if a ticket was created, else None
    """
    history    = history or []
    steps:     list[dict] = []
    tools_used: list[str] = []
    last_text  = ""
    created_ticket: Optional[dict] = None

    # ── Fast path: conversational messages skip the agent loop entirely ───────
    if _is_conversational(user_message):
        last_text = await chat(
            user_message=user_message,
            system_prompt=_CONVO_SYSTEM,
            temperature=0.7,
            max_tokens=150,
        )
        return {
            "answer":         last_text.strip(),
            "steps":          [],
            "tools_used":     [],
            "created_ticket": None,
        }

    system_prompt = AGENT_SYSTEM_PROMPT.replace("{max_iter}", str(max_iterations))

    # Track (action, params_hash) to detect and break duplicate tool calls
    seen_calls: set[str] = set()

    for i in range(max_iterations):
        prompt   = _build_iteration_prompt(user_message, history, steps)
        response = await chat(
            user_message=prompt,
            system_prompt=system_prompt,
            temperature=0.25,
            max_tokens=1000,
        )
        last_text = response.strip()

        tool_call = _parse_tool_call(last_text)

        # ── Safety net: first iteration returned no tool call for a data question ──
        # If the LLM skipped tools and tried to answer from memory on iteration 0,
        # force a search so we never return hallucinated ticket data.
        _NEEDS_TOOL_RE = re.compile(
            r"\b(ticket|bug|issue|sprint|blocker|open|closed|done|progress|"
            r"decision|wiki|standup|assignee|priority|status|blocked|"
            r"timesheet|time|hours|logged|log|worklog|days|missing|entry|entries)\b",
            re.IGNORECASE,
        )
        _TIMESHEET_RE = re.compile(
            r"\b(timesheet|time.?sheet|hours|logged|worklog|days.*(not|miss)|"
            r"(not|miss).*(log|day)|log.*time|time.*log)\b",
            re.IGNORECASE,
        )
        if tool_call is None and i == 0 and _NEEDS_TOOL_RE.search(user_message):
            if _TIMESHEET_RE.search(user_message):
                logger.info("Agent skipped tool on timesheet question — injecting get_timesheet")
                tool_call = {
                    "action":     "get_timesheet",
                    "parameters": {"days": 14},
                    "reasoning":  "auto-injected: user asked about timesheet/time logged",
                }
            else:
                logger.info("Agent returned a direct answer on iteration 0 for a data question — injecting search")
                tool_call = {
                    "action":     "search",
                    "parameters": {"query": user_message[:200], "scope": "all"},
                    "reasoning":  "auto-injected: user asked a data question but agent skipped tool call",
                }

        # ── Final answer ──────────────────────────────────────────────────────
        if tool_call is None:
            steps.append({
                "iteration":  i,
                "final_text": last_text,
                "timestamp":  datetime.utcnow().isoformat(),
            })
            break

        # ── Tool call ─────────────────────────────────────────────────────────
        action    = str(tool_call.get("action", ""))
        params    = tool_call.get("parameters") or {}
        reasoning = str(tool_call.get("reasoning", ""))

        # Deduplication guard: if the same tool already succeeded, force final answer immediately
        already_succeeded = {
            s["tool_call"]["action"]
            for s in steps
            if s.get("tool_call") and s.get("tool_result", {}).get("success")
        }
        call_fingerprint = f"{action}:{json.dumps(params, sort_keys=True)}"
        if call_fingerprint in seen_calls or action in already_succeeded:
            logger.warning(f"Agent repeated tool call '{action}' with same params — forcing final answer")
            summary_prompt = (
                _build_iteration_prompt(user_message, history, steps)
                + "\n\nYou now have all the data you need. "
                  "Write your FINAL ANSWER as plain text only — no JSON, no tool calls, no Status/Next labels."
            )
            raw_summary = await chat(
                user_message=summary_prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=600,
            )
            # Strip any JSON the LLM might still emit despite instructions
            forced_text = re.sub(r"```[\s\S]*?```", "", raw_summary).strip()
            forced_text = re.sub(r"\{[^{}]*\"action\"[^{}]*\}", "", forced_text).strip()
            if not forced_text:
                forced_text = "Here are the results I found:\n\n" + "\n".join(
                    f"- {s['tool_result']['data']}" for s in steps
                    if s.get("tool_result", {}).get("success")
                )
            last_text = forced_text
            steps.append({
                "iteration":  i,
                "final_text": last_text,
                "timestamp":  datetime.utcnow().isoformat(),
            })
            break
        seen_calls.add(call_fingerprint)

        step: dict = {
            "iteration": i,
            "tool_call": {
                "action":     action,
                "parameters": params,
                "reasoning":  reasoning,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }

        tool_result = await _execute_tool(action, params, user, db)
        step["tool_result"] = tool_result
        steps.append(step)
        tools_used.append(action)

        # Track ticket creation for the caller's UI
        if action == "create_ticket" and tool_result["success"]:
            d = tool_result["data"]
            created_ticket = {
                "id":         d.get("key", "TRK-???"),
                "title":      str(params.get("title", "")),
                "priority":   str(params.get("priority", "Medium")),
                "issue_type": str(params.get("issue_type", "Task")),
            }

    # Exhausted iterations without a final-answer step
    if not any("final_text" in s for s in steps):
        done = [s["tool_call"]["action"] for s in steps if "tool_call" in s]
        last_text = (
            "I've completed the requested steps. Summary:\n\n"
            + "\n".join(f"- {t}: ✓" for t in done)
        )

    return {
        "answer":         last_text,
        "steps":          steps,
        "tools_used":     tools_used,
        "created_ticket": created_ticket,
    }
