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
    "You are NOVA, an AI assistant for Trackly. "
    "Reply naturally and concisely to the user's message."
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


AGENT_SYSTEM_PROMPT = """You are NOVA, an autonomous AI project management agent for Trackly.
You have access to tools and must use them to answer questions accurately.

AVAILABLE TOOLS:

### get_ticket
Fetch a ticket by its exact key (e.g. TRKLY-1). Use this when the user mentions a specific ticket key.
Parameters:
  key (string, required): Exact ticket key, e.g. "TRKLY-1"

### update_ticket_status
Update the status of a ticket by its key.
Valid statuses: Backlog, To Do, In Progress, In Review, Done, Blocked.
Parameters:
  key (string, required): Ticket key, e.g. "TRKLY-1"
  status (string, required): New status — must be one of the valid values above

### search
Search the project knowledge base for tickets, wiki pages, decisions, and standups.
Use this when the user does NOT provide a specific ticket key.
Parameters:
  query (string, required): Search query text
  scope (string): 'all' (default), 'tickets', or 'wiki'

### rag_query
Ask a natural-language question against the full RAG index with source citations.
Better than raw search for synthesis or summary questions.
Parameters:
  question (string, required): Natural-language question

### create_ticket
Create a new ticket in the project tracker.
Only call this when the user explicitly requests ticket creation.
Parameters:
  title (string, required): Short action-oriented title
  description (string, required): Full description with context
  priority (string): High | Medium | Low  (default Medium)
  issue_type (string): Bug | Task | Story  (default Task)

### create_wiki_page
Create a new wiki page to document decisions, processes, or fill knowledge gaps.
Only call this when the user explicitly requests wiki page creation.
Parameters:
  space_id (string, required): Wiki space ID (find via search if unknown)
  title (string, required): Page title
  content (string, required): Full page content in Markdown
  parent_id (string): Optional parent page ID for nesting

### generate_standup
Auto-generate today's standup for the current user from recent activity.
Parameters: none

RESPONSE FORMAT — follow exactly:
- To call a tool: respond with ONLY a raw JSON object, no prose, no fences:
  {"action": "tool_name", "parameters": {"key": "value"}, "reasoning": "brief reason"}
- To give a final answer: respond with plain text only (no JSON).
- NEVER mix JSON and prose. One or the other per response.
- NEVER invent facts — always use tools to retrieve data.
- After all tool calls are done, give a concise plain-text summary.
- NEVER call the same tool with the same parameters twice.
- When the user mentions a ticket key like TRKLY-1, always use get_ticket first, not search.

WHEN NOT TO USE TOOLS:
- Greetings ("hi", "hello", "hey") → reply with plain text immediately, no tool calls.
- Small talk or conversational messages → reply with plain text immediately.
- If you have already retrieved enough information → stop calling tools and give your answer.

EXAMPLES:
  User: "hi"         → "Hello! How can I help you with your project today?"
  User: "thanks"     → "You're welcome! Let me know if there's anything else."
  User: "what bugs are open?" → call search tool first, then answer from results.

ITERATION LIMIT: {max_iter} tool calls maximum. Use them wisely."""


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

    if steps:
        parts.append("\nACTIONS TAKEN SO FAR:")
        for i, s in enumerate(steps):
            tc = s.get("tool_call")
            if not tc:
                continue
            tr = s.get("tool_result", {})
            if tr.get("success"):
                result_str = json.dumps(tr.get("data", ""))[:600]
            else:
                result_str = f"ERROR: {tr.get('error', 'unknown error')}"
            params_str = json.dumps(tc.get("parameters", {}))[:200]
            parts.append(
                f"Step {i + 1}: called {tc['action']}({params_str})\n"
                f"  Result: {result_str}"
            )
        parts.append(
            "\nContinue: either call the next tool OR provide your final plain-text answer."
        )

    return "\n".join(parts)


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_tool_call(text: str) -> Optional[dict]:
    """
    Detect a JSON tool call in raw LLM output.
    Returns the parsed dict if found, None if this is a plain-text final answer.
    """
    text = text.strip()

    # 1. Fenced JSON block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            obj = json.loads(m.group(1).strip())
            if isinstance(obj.get("action"), str) and obj["action"]:
                return obj
        except json.JSONDecodeError:
            pass

    # 2. Bare JSON object with "action" key
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end > start:
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

        # Deduplication guard: if the exact same call was already made, force final answer
        call_fingerprint = f"{action}:{json.dumps(params, sort_keys=True)}"
        if call_fingerprint in seen_calls:
            logger.warning(f"Agent repeated tool call '{action}' with same params — forcing final answer")
            # Ask the LLM to summarise what it found so far
            summary_prompt = (
                _build_iteration_prompt(user_message, history, steps)
                + "\n\nYou have already retrieved this information. "
                  "Now provide your final plain-text answer based on the results above."
            )
            last_text = await chat(
                user_message=summary_prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=600,
            )
            steps.append({
                "iteration":  i,
                "final_text": last_text.strip(),
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
