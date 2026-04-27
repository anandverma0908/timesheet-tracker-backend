"""
app/api/routes/nova.py — NOVA AI endpoints.

Endpoints:
  GET  /api/nova/status                  Check provider (Ollama/Cerebras) status
  GET  /api/nova/my-work                 AI-powered My Work page (3 parallel NOVA calls)
  GET  /api/nova/my-brief                AI morning brief for the current user
  POST /api/nova/query                   NL query RAG — used by search modal
  POST /api/nova/sprint-retro/:id        Generate sprint retrospective markdown
  POST /api/nova/release-notes/:id       Generate release notes markdown
  POST /api/nova/standup/generate        Generate standup for a user
  GET  /api/nova/standup/today           Get own standup for today
  GET  /api/nova/standup/team            Get all team standups (manager+)
  PUT  /api/nova/standup/:id             Edit own standup
  GET  /api/nova/knowledge-gaps          List detected knowledge gaps (PM+)
  POST /api/nova/spaces-brief/:pod       EOS Project Brief for SummaryTab (3 insight signals)
  GET  /api/nova/self-org                Self-organisation suggestions across pods
  POST /api/nova/sprint-draft/:pod       AI-drafted sprint backlog for a pod
"""

import hashlib
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_manager_up
from app.core.config import settings
from app.models.user import User
from app.schemas.search import NovaQueryRequest, NovaQueryOut

router = APIRouter(prefix="/api/nova", tags=["nova"])


# ── Schemas ────────────────────────────────────────────────────────────────

class StandupGenerateRequest(BaseModel):
    user_id:       Optional[str]  = None   # admin/manager can generate for others
    standup_date:  Optional[str]  = None   # ISO date, defaults to today


class StandupUpdateRequest(BaseModel):
    yesterday: Optional[str] = None
    today:     Optional[str] = None
    blockers:  Optional[str] = None
    is_shared: Optional[bool] = None


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/status")
async def nova_status(user: User = Depends(get_current_user)):
    """Check if NOVA is available — reflects active provider (Ollama or Cerebras)."""
    from app.ai.nova import is_available
    available = is_available()
    provider  = settings.nova_provider
    model     = settings.cerebras_model if provider == "cerebras" else settings.nova_model
    return {
        "available":  available,
        "provider":   provider,
        "model":      model,
        "ollama_url": settings.nova_base_url if provider == "ollama" else None,
        "status":     "online" if available else "offline",
    }


# ── My Work helpers ───────────────────────────────────────────────────────────

import json as _json
import re  as _re


def _compute_data_hash(*parts) -> str:
    """Deterministic SHA-256 hash of input data for cache invalidation."""
    payload = "|".join(str(p) for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_nova_json(text: Optional[str]):
    """Extract JSON from NOVA response — handles markdown fences and extra prose."""
    if not text:
        return None
    for s, e in [("[", "]"), ("{", "}")]:
        start, end = text.find(s), text.rfind(e)
        if start != -1 and end > start:
            try:
                return _json.loads(text[start:end + 1])
            except Exception:
                pass
    m = _re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        try:
            return _json.loads(m.group(1))
        except Exception:
            pass
    return None


def _fallback_rank(tickets: list, today) -> list:
    """Deterministic rank when NOVA is unavailable."""
    from datetime import date as _date
    PRIORITY = {"Highest": 5, "High": 4, "Medium": 3, "Low": 2, "Lowest": 1}
    scored = []
    for t in tickets:
        s = PRIORITY.get(t.priority or "", 3) * 10
        if "block" in (t.status or "").lower(): s += 100
        if t.status == "In Progress":           s += 40
        if t.due_date and t.due_date <= today:  s += 60
        stale = (today - t.jira_updated).days if t.jira_updated else 0
        s += min(stale * 2, 20)
        urgency = ("critical" if "block" in (t.status or "").lower() or (t.due_date and t.due_date < today)
                   else "high" if t.priority in ("Highest", "High")
                   else "medium" if t.status == "In Progress"
                   else "low")
        scored.append({"key": t.jira_key, "score": s, "urgency": urgency,
                       "reason": f"{t.status} · {t.priority or 'Medium'} priority",
                       "action": "Review and update status"})
    scored.sort(key=lambda x: x["score"], reverse=True)
    for i, item in enumerate(scored):
        item["rank"] = i + 1
    return scored


def _fallback_flow(wip_count: int, open_count: int) -> dict:
    flow = "scattered" if wip_count > 4 else "disrupted" if wip_count > 2 else "focused"
    rec  = (f"High WIP ({wip_count}) — pick top 2 and defer the rest."
            if wip_count > 3 else f"Good focus — {wip_count} in progress.")
    return {"context_switches": wip_count, "flow_state": flow,
            "recommendation": rec, "focus_on": []}


def _fallback_blockers(tickets: list, today) -> list:
    preds = []
    for t in tickets:
        if "block" in (t.status or "").lower():
            continue
        stale = (today - t.jira_updated).days if t.jira_updated else 0
        if stale >= 3:
            preds.append({
                "key": t.jira_key,
                "reason": f"No update for {stale} days — external dependency at risk",
                "hours_until_block": max(8, 48 - stale * 6),
                "confidence": min(0.9, 0.4 + stale * 0.1),
            })
    return sorted(preds, key=lambda x: x["hours_until_block"])[:3]


def _compute_sprint_stats(open_tickets: list, sprint_tickets: list, active_sprint, DONE: set, today) -> Optional[dict]:
    if not active_sprint:
        return None
    my_sprint_tix = [t for t in open_tickets if getattr(t, "sprint_id", None) == active_sprint.id]
    committed = sum(t.story_points or 0 for t in sprint_tickets)
    done_pts  = sum(t.story_points or 0 for t in sprint_tickets if t.status in DONE)
    remaining = committed - done_pts
    wip_count = len([t for t in open_tickets if t.status == "In Progress"])

    days_left = 0
    if active_sprint.end_date:
        days_left = max(0, (active_sprint.end_date - today).days)

    total_days = 14
    if active_sprint.start_date and active_sprint.end_date:
        total_days = max(1, (active_sprint.end_date - active_sprint.start_date).days)

    elapsed = max(1, total_days - days_left)
    pace    = done_pts / elapsed if elapsed > 0 else 0
    needed  = remaining / days_left if days_left > 0 else 0
    prob    = min(100, int((pace / needed * 100) if needed > 0 else 100))

    status  = "on_track" if prob >= 80 else "at_risk" if prob >= 50 else "off_track"
    coaching = {
        "on_track":  f"On track — {days_left}d left, {remaining} pts remaining.",
        "at_risk":   f"At risk — consider scope reduction. {remaining} pts, {days_left}d left.",
        "off_track": f"Off track — {remaining} pts in {days_left}d at {pace:.1f} pts/day.",
    }[status]
    if wip_count > 3:
        coaching += f" {wip_count} WIP tickets — context switch risk."

    return {
        "committed": committed, "completed": done_pts, "remaining": remaining,
        "probability": prob, "days_left": days_left, "wip_count": wip_count,
        "status": status, "coaching": coaching,
        "sprint_name": active_sprint.name,
    }


def _compute_time_energy(open_tickets: list, worklogs: list, today) -> dict:
    from datetime import timedelta
    total_logged    = sum(w.hours or 0 for w in worklogs)
    total_estimated = sum(t.original_estimate_hours or 0 for t in open_tickets)
    overrun_count   = sum(
        1 for t in open_tickets
        if (t.original_estimate_hours or 0) > 0
        and (t.hours_spent or 0) > (t.original_estimate_hours or 0) * 1.3
    )

    # Last 5 business days
    biz_days = []
    d = today
    while len(biz_days) < 5:
        if d.weekday() < 5:
            biz_days.append(d)
        d = d - timedelta(days=1)
    biz_days.reverse()

    wl_by_date: dict = {}
    for w in worklogs:
        if w.log_date:
            wl_by_date[w.log_date] = wl_by_date.get(w.log_date, 0) + (w.hours or 0)

    velocity_by_day = [round(wl_by_date.get(day, 0), 1) for day in biz_days]
    focus_score     = min(100, max(0, 100 - overrun_count * 15 -
                                   max(0, (sum(1 for t in open_tickets if t.status == "In Progress") - 2) * 10)))

    return {
        "total_logged":    round(total_logged, 1),
        "total_estimated": round(total_estimated, 1),
        "overrun_count":   overrun_count,
        "velocity_by_day": velocity_by_day,
        "peak_window":     "9am — 12pm",
        "focus_score":     focus_score,
    }


def _recent_activity(open_tickets: list, today) -> list:
    from datetime import timedelta
    events = []
    for t in open_tickets[:8]:
        stale = (today - t.jira_updated).days if t.jira_updated else 0
        ev_type = ("blocker" if "block" in (t.status or "").lower()
                   else "status" if stale < 1
                   else "assign")
        changes = {
            "blocker": "marked as blocked",
            "status":  f"moved to {t.status}",
            "assign":  f"assigned to {t.assignee or 'you'}",
        }
        time_label = (f"{stale}d ago" if stale > 0 else "today")
        events.append({
            "key": t.jira_key, "summary": t.summary,
            "change": changes[ev_type], "time": time_label, "type": ev_type,
        })
    return events


def _serialize_ticket(t) -> dict:
    return {
        "key":                      t.jira_key,
        "summary":                  t.summary,
        "status":                   t.status,
        "priority":                 t.priority,
        "issue_type":               t.issue_type,
        "assignee":                 t.assignee,
        "assignee_email":           t.assignee_email,
        "pod":                      t.pod,
        "client":                   t.client,
        "story_points":             t.story_points,
        "hours_spent":              t.hours_spent or 0,
        "original_estimate_hours":  t.original_estimate_hours or 0,
        "remaining_estimate_hours": t.remaining_estimate_hours or 0,
        "due_date":                 t.due_date.isoformat() if t.due_date else None,
        "sprint_id":                t.sprint_id,
        "labels":                   t.labels or [],
        "url":                      t.url,
        "updated":                  t.jira_updated.isoformat() if t.jira_updated else None,
        "created":                  t.jira_created.isoformat() if t.jira_created else None,
        "project_key":              t.project_key,
        "project_name":             t.project_name,
    }


@router.get("/my-work")
async def get_my_work(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """AI-first My Work endpoint — 3 parallel NOVA calls + deterministic stats."""
    import asyncio
    from datetime import date, datetime, timedelta
    from app.ai.nova import chat
    from app.models.ticket import JiraTicket, Worklog
    from app.models.sprint import Sprint as SprintModel
    from app.core import cache as _cache

    DONE  = {"Done", "Closed", "Resolved", "Won't Fix", "Duplicate", "Cancelled", "Rejected"}
    today = date.today()
    now   = datetime.now()

    # ── DB queries ────────────────────────────────────────────────────────────
    all_tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id    == user.org_id,
        JiraTicket.assignee  == user.name,
        JiraTicket.is_deleted == False,
    ).all()
    open_tickets = [t for t in all_tickets if (t.status or "") not in DONE]

    active_sprint = db.query(SprintModel).filter(
        SprintModel.org_id  == user.org_id,
        SprintModel.status  == "active",
    ).first()

    sprint_tickets: list = []
    if active_sprint:
        sprint_tickets = db.query(JiraTicket).filter(
            JiraTicket.sprint_id == active_sprint.id,
            JiraTicket.org_id    == user.org_id,
            JiraTicket.assignee  == user.name,
        ).all()

    cutoff   = today - timedelta(days=14)
    worklogs = db.query(Worklog).join(JiraTicket).filter(
        JiraTicket.org_id   == user.org_id,
        JiraTicket.assignee == user.name,
        Worklog.log_date    >= cutoff,
    ).all()

    # ── Deterministic stats ───────────────────────────────────────────────────
    sprint_risk  = _compute_sprint_stats(open_tickets, sprint_tickets, active_sprint, DONE, today)
    time_energy  = _compute_time_energy(open_tickets, worklogs, today)
    activity     = _recent_activity(open_tickets, today)

    # ── Build NOVA context ────────────────────────────────────────────────────
    wip_tickets     = [t for t in open_tickets if t.status == "In Progress"]
    blocked_tickets = [t for t in open_tickets if "block" in (t.status or "").lower()]
    overdue_tickets = [t for t in open_tickets if t.due_date and t.due_date < today]

    # Sort by severity for context window
    priority_order = sorted(
        open_tickets,
        key=lambda t: (
            ("block" in (t.status or "").lower()) * 3 +
            (t.status == "In Progress") * 2 +
            (bool(t.due_date and t.due_date <= today)) * 2
        ),
        reverse=True,
    )[:10]

    ticket_ctx = "\n".join(
        f"- {t.jira_key} | {t.status} | P:{t.priority or 'Medium'} | "
        f"SP:{t.story_points or 0} | Due:{t.due_date or 'none'} | "
        f"Stale:{(today - t.jira_updated).days if t.jira_updated else 0}d | "
        f"{(t.summary or '')[:60]}"
        for t in priority_order
    ) or "No open tickets."

    days_left    = sprint_risk["days_left"]  if sprint_risk else 0
    sprint_ctx   = (f"Sprint: {sprint_risk['sprint_name']}, {days_left}d left"
                    if sprint_risk else "No active sprint")
    time_ctx     = f"Hour: {now.hour}, Day: {now.strftime('%A')}"
    first_name   = (user.name or "there").split()[0]

    greeting = ("Good morning" if now.hour < 12
                else "Good afternoon" if now.hour < 17
                else "Good evening")

    # ── NOVA prompts ──────────────────────────────────────────────────────────
    rank_prompt = f"""Rank these engineering tickets by urgency for {first_name}. Today: {today}. {sprint_ctx}.

{ticket_ctx}

Return ONLY a JSON array — no prose, no markdown fences:
[{{"key":"...","rank":1,"score":85,"urgency":"critical","reason":"why ranked first","action":"first step to take"}}]

urgency: critical=blocked/overdue, high=due soon/sprint risk, medium=in progress, low=todo.
Rank: blocked > overdue > sprint-deadline risk > priority > staleness."""

    flow_prompt = f"""Analyse this engineer's flow state. {time_ctx}.
WIP ({len(wip_tickets)}): {', '.join(t.jira_key for t in wip_tickets[:5]) or 'none'}
Blocked ({len(blocked_tickets)}): {', '.join(t.jira_key for t in blocked_tickets[:3]) or 'none'}
Open total: {len(open_tickets)}. {sprint_ctx}.

Return ONLY JSON — no prose:
{{"context_switches":{len(wip_tickets)},"flow_state":"focused|disrupted|scattered","recommendation":"one actionable sentence","focus_on":["KEY1","KEY2"]}}"""

    blocker_prompt = f"""Predict which tickets may get blocked soon. Today: {today}. {sprint_ctx}.

{ticket_ctx}

Return ONLY a JSON array (exclude already-blocked tickets, max 3):
[{{"key":"...","reason":"specific risk reason","hours_until_block":24,"confidence":0.75}}]"""

    _no_ticket_rule = (
        "There are NO open tickets. Do NOT mention, invent, or reference any ticket key or number. Say the slate is clear."
        if not open_tickets else
        f"Mention the most urgent ticket by key. Only use keys from this list: {', '.join(t.jira_key for t in priority_order)}. Never invent a key."
    )
    brief_prompt = f"""{greeting}, {first_name}. {time_ctx}. {sprint_ctx}.
Open: {len(open_tickets)}, WIP: {len(wip_tickets)}, Blocked: {len(blocked_tickets)}, Overdue: {len(overdue_tickets)}.

Write 2-3 sentences. Be specific, warm, actionable. Flag blockers or sprint risk if present.
{_no_ticket_rule}"""

    # ── Stable cache key for AI outputs ──────────────────────────────────────
    ai_cache_key = f"my_work_ai:{user.id}:{_compute_data_hash(ticket_ctx, sprint_ctx, len(open_tickets), len(wip_tickets), len(blocked_tickets))}"
    cached_ai = _cache.get(ai_cache_key)

    # ── Parallel NOVA calls ───────────────────────────────────────────────────
    async def _safe_nova(prompt: str, label: str, tokens: int = 400) -> Optional[str]:
        try:
            return await asyncio.wait_for(
                chat(user_message=prompt, temperature=0, max_tokens=tokens),
                timeout=14.0,
            )
        except Exception:
            return None

    if cached_ai:
        rank_raw, flow_raw, blocker_raw, brief_raw = (
            cached_ai.get("rank"), cached_ai.get("flow"),
            cached_ai.get("blocker"), cached_ai.get("brief"),
        )
    else:
        rank_raw, flow_raw, blocker_raw, brief_raw = await asyncio.gather(
            _safe_nova(rank_prompt,    "rank",    500),
            _safe_nova(flow_prompt,    "flow",    200),
            _safe_nova(blocker_prompt, "blocker", 300),
            _safe_nova(brief_prompt,   "brief",   180),
        )
        _cache.set(ai_cache_key, {
            "rank": rank_raw, "flow": flow_raw,
            "blocker": blocker_raw, "brief": brief_raw,
        }, ttl_seconds=4 * 3600)

    # ── Parse + fallback ──────────────────────────────────────────────────────
    priority_queue      = _parse_nova_json(rank_raw)
    flow_analysis       = _parse_nova_json(flow_raw)
    blocker_predictions = _parse_nova_json(blocker_raw)

    if not isinstance(priority_queue, list):
        priority_queue = _fallback_rank(priority_order, today)
    if not isinstance(flow_analysis, dict):
        flow_analysis = _fallback_flow(len(wip_tickets), len(open_tickets))
    if not isinstance(blocker_predictions, list):
        blocker_predictions = _fallback_blockers(open_tickets, today)

    # Ensure all AI-generated key references belong to the current user's tickets only
    user_keys = {t.jira_key for t in open_tickets}
    blocker_predictions = [p for p in blocker_predictions if p.get("key") in user_keys]
    priority_queue      = [p for p in priority_queue      if p.get("key") in user_keys]
    if isinstance(flow_analysis, dict) and "focus_on" in flow_analysis:
        flow_analysis["focus_on"] = [k for k in (flow_analysis["focus_on"] or []) if k in user_keys]

    # Ensure ranks are numbered
    for i, item in enumerate(priority_queue):
        if "rank" not in item:
            item["rank"] = i + 1

    brief_text = brief_raw or (
        f"{greeting}, {first_name}. You have {len(open_tickets)} open tickets."
        + (f" {len(blocked_tickets)} blocked." if blocked_tickets else "")
        + (f" Start with **{priority_order[0].jira_key}**." if priority_order else "")
    )

    # ── Brief chips ───────────────────────────────────────────────────────────
    chips = []
    if blocked_tickets:
        chips.append({"label": f"{len(blocked_tickets)} blocked", "type": "critical"})
    if overdue_tickets:
        chips.append({"label": f"{len(overdue_tickets)} overdue", "type": "warning"})
    if sprint_risk and sprint_risk["probability"] < 80:
        label = "Sprint at risk" if sprint_risk["probability"] >= 50 else "Sprint off track"
        chips.append({"label": label, "type": "warning" if sprint_risk["probability"] >= 50 else "critical"})
    if len(wip_tickets) > 3:
        chips.append({"label": f"{len(wip_tickets)} WIP — focus risk", "type": "info"})
    if priority_order:
        chips.append({"label": f"Start: {priority_order[0].jira_key}", "type": "action"})

    return {
        "tickets":             [_serialize_ticket(t) for t in open_tickets],
        "priority_queue":      priority_queue,
        "flow_analysis":       flow_analysis,
        "blocker_predictions": blocker_predictions,
        "sprint_risk":         sprint_risk,
        "time_energy":         time_energy,
        "brief":               brief_text,
        "brief_chips":         chips,
        "recent_activity":     activity,
    }


class GenerateRequest(BaseModel):
    prompt: str
    system_prompt: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 800


@router.post("/generate")
async def nova_generate(
    body: GenerateRequest,
    user: User = Depends(get_current_user),
):
    """Direct LLM call — no RAG. Used for ticket structuring, doc generation, etc."""
    from app.ai.nova import chat
    try:
        answer = await chat(
            user_message=body.prompt,
            system_prompt=body.system_prompt,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(503, f"NOVA is unavailable: {e}")


class AgentHistoryItem(BaseModel):
    role:    str   # "user" | "assistant"
    content: str


class AgentRequest(BaseModel):
    message:        str
    history:        list[AgentHistoryItem] = []
    max_iterations: int = 8


@router.post("/agent")
async def nova_agent(
    body: AgentRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """
    NOVA Agent — autonomous multi-step task execution.

    Runs the agent loop server-side: LLM decides which tools to call,
    tools execute against the real DB, results feed back into the next
    LLM call until a plain-text final answer is produced.

    Returns: {answer, steps, tools_used, created_ticket}
    """
    from app.ai.agent import run_agent_loop

    history = [{"role": h.role, "content": h.content} for h in body.history]
    max_iter = max(1, min(body.max_iterations, 8))  # clamp 1–8

    try:
        result = await run_agent_loop(
            user_message=body.message,
            user=user,
            db=db,
            history=history,
            max_iterations=max_iter,
        )
        return result
    except Exception as e:
        raise HTTPException(503, f"Agent loop failed: {e}")


@router.post("/query", response_model=NovaQueryOut)
async def nova_query(
    body: NovaQueryRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """RAG + keyword search with full user/project context injected."""
    from app.ai.search import nl_query
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint as SprintModel
    from datetime import date

    try:
        # ── Build live project context ────────────────────────────────────────
        DONE = {"Done","Closed","Resolved","Won't Fix","Duplicate","Cancelled","Rejected"}
        today = date.today()

        all_tix = db.query(JiraTicket).filter(
            JiraTicket.org_id    == user.org_id,
            JiraTicket.is_deleted == False,
        ).all()
        open_tix    = [t for t in all_tix if (t.status or "") not in DONE]
        my_tix      = [t for t in open_tix if t.assignee == user.name]
        blocked     = [t for t in open_tix if "block" in (t.status or "").lower()]
        overdue     = [t for t in open_tix if t.due_date and t.due_date < today]

        sprint = db.query(SprintModel).filter(
            SprintModel.org_id == user.org_id,
            SprintModel.status == "active",
        ).first()

        # Compact context string injected into every Nova query
        ctx_lines = [
            f"Engineer asking: {user.name} (role: {user.role or 'engineer'}).",
            f"Project has {len(open_tix)} open tickets total; {len(my_tix)} assigned to {user.name}.",
        ]
        if blocked:
            ctx_lines.append(f"Currently blocked: {', '.join(t.jira_key + ' (' + (t.summary or '')[:40] + ')' for t in blocked[:4])}.")
        if overdue:
            ctx_lines.append(f"Overdue: {', '.join(t.jira_key for t in overdue[:4])}.")
        if sprint:
            days_left = max(0, (sprint.end_date - today).days) if sprint.end_date else "?"
            ctx_lines.append(f"Active sprint: '{sprint.name}' — {days_left} days left.")
        if my_tix:
            ctx_lines.append(
                "My open tickets: " +
                "; ".join(f"{t.jira_key} [{t.status}] {(t.summary or '')[:50]}" for t in my_tix[:6]) + "."
            )

        user_context = " ".join(ctx_lines)

        data    = await nl_query(body.query, user.org_id, user_context=user_context)
        return NovaQueryOut(answer=data["answer"], sources=data["sources"])

    except Exception as e:
        raise HTTPException(503, f"NOVA is unavailable: {e}")


@router.post("/sprint-retro/{sprint_id}")
async def generate_retro(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Generate a structured sprint retrospective markdown via NOVA."""
    from app.ai.documents import generate_sprint_retro

    result = await generate_sprint_retro(sprint_id, user.org_id, db)
    return {"sprint_id": sprint_id, "retro": result}


@router.post("/release-notes/{sprint_id}")
async def generate_release_notes(
    sprint_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Generate user-facing release notes markdown via NOVA."""
    from app.ai.documents import generate_release_notes

    result = await generate_release_notes(sprint_id, user.org_id, db)
    return {"sprint_id": sprint_id, "release_notes": result}


@router.post("/standup/generate")
async def generate_standup(
    body: StandupGenerateRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Generate a NOVA-powered standup for the current user (or another user for managers)."""
    from app.ai.documents import generate_standup as _gen

    # Managers can generate for other users; others only for themselves
    target_id = body.user_id or user.id
    if target_id != user.id and user.role not in ("admin", "engineering_manager"):
        raise HTTPException(403, "Only managers can generate standups for others")

    standup_date = body.standup_date or date.today().isoformat()

    try:
        result = await _gen(target_id, user.org_id, standup_date, db)
    except Exception as e:
        raise HTTPException(500, f"Standup generation failed: {e}")

    if "error" in result:
        raise HTTPException(404, result["error"])

    return result


@router.get("/standup/today")
async def get_my_standup(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Return the current user's standup for today, if it exists."""
    from app.models.sprint import Standup

    today = date.today()
    standup = db.query(Standup).filter(
        Standup.user_id == user.id,
        Standup.date    == today,
    ).first()

    if not standup:
        return {"message": "No standup for today yet. Use POST /api/nova/standup/generate."}

    return {
        "id":             standup.id,
        "user_id":        standup.user_id,
        "engineer":       user.name,
        "engineer_email": user.email,
        "pod":            user.pod or "",
        "date":           standup.date.isoformat(),
        "yesterday":      standup.yesterday or "",
        "today":          standup.today or "",
        "blockers":       standup.blockers or "",
        "shared":         standup.is_shared,
        "created_at":     standup.date.isoformat(),
    }


@router.get("/standup/team")
async def get_team_standups(
    standup_date: Optional[str] = Query(None, description="ISO date, defaults to today"),
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Return all team standups for a given date (managers and above)."""
    from app.models.sprint import Standup
    from app.models.user import User as UserModel

    target_date = date.fromisoformat(standup_date) if standup_date else date.today()

    # Admins are excluded from team standup views entirely
    admin_ids = [
        u.id for u in db.query(UserModel).filter(
            UserModel.org_id == user.org_id,
            UserModel.role   == "admin",
        ).all()
    ]

    # Managers only see standups of their direct reports
    if user.role == "engineering_manager":
        visible_user_ids = [
            u.id for u in db.query(UserModel).filter(
                UserModel.org_id      == user.org_id,
                UserModel.reporting_to == str(user.id),
            ).all()
        ]
    else:
        # Admin role (get_manager_up allows admin too) — sees everyone except other admins
        visible_user_ids = None

    query = db.query(Standup).filter(
        Standup.org_id == user.org_id,
        Standup.date   == target_date,
        ~Standup.user_id.in_(admin_ids),
    )
    if visible_user_ids is not None:
        # Manager sees their own standup + direct reports
        query = query.filter(Standup.user_id.in_(visible_user_ids + [user.id]))

    standups = query.all()

    result = []
    for s in standups:
        member = db.query(UserModel).filter(UserModel.id == s.user_id).first()
        result.append({
            "id":             s.id,
            "user_id":        s.user_id,
            "engineer":       member.name if member else None,
            "engineer_email": member.email if member else None,
            "pod":            member.pod  if member else None,
            "date":           s.date.isoformat(),
            "yesterday":      s.yesterday,
            "today":          s.today,
            "blockers":       s.blockers,
            "shared":         s.is_shared,
        })

    return {"date": target_date.isoformat(), "standups": result}


@router.put("/standup/{standup_id}")
async def update_standup(
    standup_id: str,
    body: StandupUpdateRequest,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Engineer edits their own standup (managers can edit any)."""
    from app.models.sprint import Standup

    standup = db.query(Standup).filter(Standup.id == standup_id).first()
    if not standup:
        raise HTTPException(404, "Standup not found")

    # Enforce ownership (unless manager/admin)
    if standup.user_id != user.id and user.role not in ("admin", "engineering_manager"):
        raise HTTPException(403, "You can only edit your own standup")

    if body.yesterday is not None:
        standup.yesterday = body.yesterday
    if body.today is not None:
        standup.today = body.today
    if body.blockers is not None:
        standup.blockers = body.blockers
    if body.is_shared is not None:
        standup.is_shared = body.is_shared

    db.commit()
    db.refresh(standup)

    return {
        "id":        standup.id,
        "user_id":   standup.user_id,
        "date":      standup.date.isoformat(),
        "yesterday": standup.yesterday,
        "today":     standup.today,
        "blockers":  standup.blockers,
        "is_shared": standup.is_shared,
    }


@router.get("/knowledge-gaps")
async def knowledge_gaps(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Return detected knowledge gaps for the org (latest run)."""
    from app.models.sprint import KnowledgeGap
    import json

    gaps = db.query(KnowledgeGap).filter(
        KnowledgeGap.org_id == user.org_id,
    ).order_by(KnowledgeGap.detected_at.desc()).limit(50).all()

    return [
        {
            "id":              g.id,
            "topic":           g.topic,
            "ticket_count":    g.ticket_count,
            "wiki_coverage":   g.wiki_coverage,
            "example_tickets": json.loads(g.example_tickets) if g.example_tickets else [],
            "suggestion":      g.suggestion,
            "detected_at":     g.detected_at.isoformat() if g.detected_at else None,
        }
        for g in gaps
    ]


@router.get("/my-brief")
async def get_my_brief(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """AI-generated personalised morning brief for the current user via NOVA."""
    from app.ai.nova import chat
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint as SprintModel
    from datetime import datetime
    from app.core import cache as _cache

    DONE = {"Done", "Closed", "Resolved", "Won't Fix", "Duplicate", "Cancelled", "Rejected"}

    # Fetch user's open tickets
    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id  == user.org_id,
        JiraTicket.assignee == user.name,
    ).all()
    open_tickets = [t for t in tickets if t.status not in DONE]

    # Active sprint
    active_sprint = db.query(SprintModel).filter(
        SprintModel.org_id == user.org_id,
        SprintModel.status == "active",
    ).first()

    # Derive key numbers
    blocked     = [t for t in open_tickets if "block" in (t.status or "").lower()]
    in_progress = [t for t in open_tickets if t.status == "In Progress"]
    overdue     = [t for t in open_tickets if t.due_date and t.due_date < datetime.utcnow().date()]

    blocker_count   = len(blocked)
    wip_count       = len(in_progress)
    overdue_count   = len(overdue)

    # Sprint probability (simple pace estimate)
    sprint_probability = None  # type: Optional[int]
    sprint_name = None         # type: Optional[str]
    days_left = None           # type: Optional[int]
    if active_sprint:
        sprint_name = active_sprint.name
        now  = datetime.utcnow().date()
        end  = active_sprint.end_date
        start = active_sprint.start_date
        if end and start:
            days_left  = max(0, (end - now).days)
            total_days = max(1, (end - start).days)
            elapsed    = max(1, total_days - days_left)
            sp_tickets = db.query(JiraTicket).filter(
                JiraTicket.sprint_id == active_sprint.id,
                JiraTicket.org_id    == user.org_id,
                JiraTicket.assignee  == user.name,
            ).all()
            committed = sum(t.story_points or 0 for t in sp_tickets)
            done_pts  = sum(t.story_points or 0 for t in sp_tickets if t.status in DONE)
            remaining = committed - done_pts
            pace      = done_pts / elapsed if elapsed > 0 else 0
            needed    = remaining / days_left if days_left > 0 else 0
            sprint_probability = min(100, int((pace / needed * 100) if needed > 0 else 100))

    # Top priority ticket
    sorted_tickets = sorted(
        open_tickets,
        key=lambda t: (
            ("block" in (t.status or "").lower()) * 3 +
            (t.status == "In Progress") * 2 +
            ((t.due_date is not None and t.due_date <= datetime.utcnow().date())) * 2
        ),
        reverse=True,
    )
    top_ticket = sorted_tickets[0] if sorted_tickets else None

    # Build ticket summary for NOVA context
    ticket_lines = []
    for t in sorted_tickets[:8]:
        line = f"- [{t.jira_key}] {t.summary} | status: {t.status} | priority: {t.priority or 'Medium'}"
        if t.due_date:
            line += f" | due: {t.due_date}"
        ticket_lines.append(line)
    ticket_ctx = "\n".join(ticket_lines) if ticket_lines else "No open tickets."

    sprint_ctx = (
        f"Active sprint: {sprint_name}, {days_left} days left, completion probability ~{sprint_probability}%."
        if sprint_probability is not None else "No active sprint."
    )

    first = (user.name or "there").split()[0]

    # Stable cache key based on ticket state — same data → same brief across refreshes
    brief_cache_key = f"my_brief:{user.id}:{_compute_data_hash(ticket_ctx, sprint_ctx, blocker_count, wip_count, overdue_count)}"
    cached_brief = _cache.get(brief_cache_key)

    no_ticket_instruction = (
        "There are NO open tickets. Do NOT mention, invent, or reference any ticket key or number whatsoever."
        if not open_tickets else
        "ONLY mention ticket keys that appear verbatim in the list above. Never invent any key not in the list."
    )

    prompt = f"""You are EOS. Write a personalised morning brief for {first}.

Open tickets ({len(open_tickets)} total):
{ticket_ctx}

{sprint_ctx}
Blockers: {blocker_count}, WIP: {wip_count}, Overdue: {overdue_count}.

Rules:
- {no_ticket_instruction}
- 2-3 sentences max. Conversational, like a smart teammate giving a quick heads-up."""

    if cached_brief:
        brief_text = cached_brief
    else:
        try:
            brief_text = await chat(
                user_message=prompt,
                temperature=0,
                max_tokens=180,
            )
            if brief_text:
                _cache.set(brief_cache_key, brief_text, ttl_seconds=4 * 3600)
        except Exception:
            brief_text = None

    if not brief_text:
        brief_text = f"Good morning, {first}. You have {len(open_tickets)} open tickets."
        if blocker_count:
            brief_text += f" {blocker_count} ticket{'s are' if blocker_count > 1 else ' is'} blocked — worth addressing first."
        if top_ticket:
            brief_text += f" Start with **{top_ticket.jira_key}** — {top_ticket.status}."

    # Insight chips (structured context for the frontend)
    chips = []
    if blocker_count:
        chips.append({"label": f"{blocker_count} blocked", "type": "critical"})
    if overdue_count:
        chips.append({"label": f"{overdue_count} overdue", "type": "warning"})
    if sprint_probability is not None and sprint_probability < 80:
        label = "Sprint at risk" if sprint_probability >= 50 else "Sprint off track"
        chips.append({"label": label, "type": "warning" if sprint_probability >= 50 else "critical"})
    if wip_count > 3:
        chips.append({"label": f"{wip_count} WIP — focus risk", "type": "info"})
    if top_ticket:
        chips.append({"label": f"Start: {top_ticket.jira_key}", "type": "action"})

    return {
        "brief":              brief_text,
        "top_ticket_key":     top_ticket.jira_key if top_ticket else None,
        "sprint_probability": sprint_probability,
        "blocker_count":      blocker_count,
        "overdue_count":      overdue_count,
        "wip_count":          wip_count,
        "open_count":         len(open_tickets),
        "chips":              chips,
    }


@router.post("/spaces-brief/{pod}")
async def spaces_brief(
    pod: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """
    EOS Project Brief for a pod's SummaryTab.
    Returns a short brief paragraph + 3 structured insight signals.
    Caches result so repeated refreshes are deterministic.
    Falls back gracefully when NOVA is unavailable.
    """
    import asyncio
    from app.ai.nova import chat
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint
    from app.models.space_brief import SpaceBrief
    from app.services.health_service import compute_health
    from datetime import date

    org_id = user.org_id
    today  = date.today()

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
    ).all()

    active_sprint = db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.pod == pod,
        Sprint.status == "active",
    ).first()

    health = compute_health(tickets, active_sprint)
    total  = len(tickets) or 1
    done   = sum(1 for t in tickets if (t.status or "").lower() in {"done", "closed", "resolved"})
    blocked = health["risk_flags"]["blocked"]
    overdue = health["risk_flags"]["overdue"]

    sprint_ctx = ""
    if active_sprint:
        sp_tix    = [t for t in tickets if getattr(t, "sprint_id", None) == active_sprint.id]
        committed = sum(t.story_points or 0 for t in sp_tix)
        done_pts  = sum(t.story_points or 0 for t in sp_tix if (t.status or "").lower() in {"done", "closed", "resolved"})
        days_left = max(0, (active_sprint.end_date - today).days) if active_sprint.end_date else 0
        sprint_ctx = (
            f"Active sprint '{active_sprint.name}': {done_pts}/{committed} pts done, {days_left}d left."
        )

    ticket_sample = "\n".join(
        f"- {t.jira_key} | {t.status} | {t.priority or 'Medium'} | {(t.summary or '')[:60]}"
        for t in sorted(tickets, key=lambda t: (t.status or ""), reverse=True)[:10]
    ) or "No tickets."

    # ── Cache key: hash of all deterministic inputs ──
    data_hash = _compute_data_hash(
        pod,
        health["health_score"],
        health["radar"],
        len(tickets), done, blocked, overdue,
        sprint_ctx,
        ticket_sample,
    )

    cached = db.query(SpaceBrief).filter(
        SpaceBrief.org_id == org_id,
        SpaceBrief.pod == pod,
    ).first()

    if cached and cached.data_hash == data_hash and cached.brief:
        return {
            "pod":             pod,
            "health_score":    health["health_score"],
            "brief":           cached.brief,
            "velocity_signal": cached.velocity_signal or "",
            "risk_signal":     cached.risk_signal or "",
            "recommendation":  cached.recommendation or "",
            "nova_powered":    True,
        }

    prompt = f"""Pod: {pod}
Health score: {health['health_score']}/100. Radar: {health['radar']}.
Tickets: {len(tickets)} total, {done} done, {blocked} blocked, {overdue} overdue.
{sprint_ctx}

Sample tickets:
{ticket_sample}

Write a concise EOS project brief (2-3 sentences) summarising this pod's status.
Then return exactly 3 insight signals in this JSON format — no prose before or after:

{{
  "brief": "...",
  "velocity_signal": "one sentence about delivery pace or sprint progress",
  "risk_signal": "one sentence about the main risk (blockers, overdue, tech debt)",
  "recommendation": "one concrete actionable recommendation for the team lead"
}}"""

    try:
        raw = await asyncio.wait_for(
            chat(user_message=prompt, temperature=0, max_tokens=350),
            timeout=15.0,
        )
        data = _parse_nova_json(raw)
        if isinstance(data, dict) and "brief" in data:
            # Upsert cache
            if not cached:
                cached = SpaceBrief(org_id=org_id, pod=pod)
                db.add(cached)
            cached.data_hash = data_hash
            cached.brief = data.get("brief", "")
            cached.velocity_signal = data.get("velocity_signal", "")
            cached.risk_signal = data.get("risk_signal", "")
            cached.recommendation = data.get("recommendation", "")
            db.commit()
            return {
                "pod":              pod,
                "health_score":     health["health_score"],
                "brief":            cached.brief,
                "velocity_signal":  cached.velocity_signal,
                "risk_signal":      cached.risk_signal,
                "recommendation":   cached.recommendation,
                "nova_powered":     True,
            }
    except Exception:
        pass

    # Deterministic fallback
    vs = ("Sprint is on pace." if (health["sprint_prediction"] or 0) >= 70
          else f"Sprint at risk — {health['sprint_prediction'] or 'unknown'}% completion predicted.")
    rs = (f"{blocked} blocked tickets require immediate attention." if blocked
          else f"Quality score {health['radar']['quality']}% — monitor bug rate.")
    rc = ("Unblock critical tickets first." if blocked >= 2
          else "Focus on completing in-progress work before pulling new tickets.")

    # Cache fallback too so it doesn't flip-flop between AI and fallback
    if not cached:
        cached = SpaceBrief(org_id=org_id, pod=pod)
        db.add(cached)
    cached.data_hash = data_hash
    cached.brief = f"{pod} pod health is {health['health_score']}/100. {done}/{len(tickets)} tickets complete."
    cached.velocity_signal = vs
    cached.risk_signal = rs
    cached.recommendation = rc
    db.commit()

    return {
        "pod":             pod,
        "health_score":    health["health_score"],
        "brief":           cached.brief,
        "velocity_signal": vs,
        "risk_signal":     rs,
        "recommendation":  rc,
        "nova_powered":    False,
    }


@router.get("/self-org")
async def self_org_suggestions(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """
    Self-organisation suggestions: recommend engineer moves between pods
    based on capacity imbalance and blocked work.
    Powers EOSIntelligencePanel → Self-Org tab.
    Manager+ only.
    """
    import asyncio
    from app.ai.nova import chat
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint
    from app.services.health_service import compute_health

    org_id = user.org_id

    # Build per-pod capacity snapshot
    pods_q = db.query(JiraTicket.pod).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.pod != None,
    ).distinct().all()

    pod_snapshots = []
    for (pod,) in pods_q:
        if not (pod or "").strip():
            continue
        tickets = db.query(JiraTicket).filter(
            JiraTicket.org_id == org_id,
            JiraTicket.pod == pod,
            JiraTicket.is_deleted == False,
        ).all()
        active_sprint = db.query(Sprint).filter(
            Sprint.org_id == org_id,
            Sprint.pod == pod,
            Sprint.status == "active",
        ).first()
        health     = compute_health(tickets, active_sprint)
        members    = list({t.assignee for t in tickets if t.assignee})
        open_count = sum(1 for t in tickets if (t.status or "").lower()
                         not in {"done", "closed", "resolved"})
        pod_snapshots.append({
            "pod":          pod,
            "health_score": health["health_score"],
            "blocked":      health["risk_flags"]["blocked"],
            "open_tickets": open_count,
            "member_count": len(members),
            "members":      members[:8],
            "velocity":     health["radar"]["velocity"],
        })

    pod_snapshots.sort(key=lambda p: p["health_score"])

    # Build NOVA prompt
    snapshot_ctx = "\n".join(
        f"- {p['pod']}: health={p['health_score']}, blocked={p['blocked']}, "
        f"open={p['open_tickets']}, members={p['member_count']}, velocity={p['velocity']}"
        for p in pod_snapshots
    )

    prompt = f"""Engineering org pod snapshot:
{snapshot_ctx}

Recommend 2-3 engineer reassignments to balance load and unblock high-risk pods.
Return ONLY a JSON array — no prose:
[{{"from_pod":"...","to_pod":"...","reason":"specific reason","confidence":0.8,"urgency":"high|medium|low"}}]

Rules:
- Only suggest moves from healthy pods (health>60) to struggling ones (health<50)
- Confidence: 0.9=very clear imbalance, 0.6=moderate signal
- urgency: high=blocked+low velocity, medium=overloaded, low=minor rebalance"""

    try:
        raw = await asyncio.wait_for(
            chat(user_message=prompt, temperature=0, max_tokens=400),
            timeout=15.0,
        )
        suggestions = _parse_nova_json(raw)
        if isinstance(suggestions, list):
            return {"suggestions": suggestions, "nova_powered": True, "pod_snapshots": pod_snapshots}
    except Exception:
        pass

    # Deterministic fallback: flag pods with health<40 and members from pods with health>70
    suggestions = []
    struggling = [p for p in pod_snapshots if p["health_score"] < 40]
    healthy    = [p for p in pod_snapshots if p["health_score"] > 70]
    for s in struggling[:2]:
        for h in healthy[:1]:
            suggestions.append({
                "from_pod":   h["pod"],
                "to_pod":     s["pod"],
                "reason":     f"{s['pod']} health is {s['health_score']}% with {s['blocked']} blockers",
                "confidence": 0.65,
                "urgency":    "high" if s["blocked"] > 2 else "medium",
            })

    return {"suggestions": suggestions, "nova_powered": False, "pod_snapshots": pod_snapshots}


@router.post("/sprint-draft/{pod}")
async def draft_sprint(
    pod: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """
    AI-drafted sprint backlog for a pod.
    Picks the best backlog tickets and suggests story points + rationale.
    Powers EOSIntelligencePanel → Sprint Draft tab.
    Manager+ only.
    """
    import asyncio
    from app.ai.nova import chat
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint
    from app.services.health_service import compute_health

    org_id = user.org_id

    # Backlog tickets for this pod (no sprint assigned)
    backlog = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.sprint_id == None,
        JiraTicket.is_deleted == False,
        JiraTicket.status.notin_(["Done", "Closed", "Resolved"]),
    ).order_by(JiraTicket.jira_updated.desc()).limit(30).all()

    if not backlog:
        return {"pod": pod, "tickets": [], "rationale": "No backlog tickets found.", "nova_powered": False}

    active_sprint = db.query(Sprint).filter(
        Sprint.org_id == org_id,
        Sprint.pod == pod,
        Sprint.status == "active",
    ).first()

    all_tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
    ).all()
    health = compute_health(all_tickets, active_sprint)

    # Build a lookup so AI responses can be validated against real DB records
    backlog_lookup = {t.jira_key: t for t in backlog}

    # Historical velocity: average completed story points across recent done sprints
    from app.models.sprint import Sprint as SprintModel
    recent_sprints = db.query(SprintModel).filter(
        SprintModel.org_id == org_id,
        SprintModel.pod == pod,
        SprintModel.status == "completed",
    ).order_by(SprintModel.end_date.desc()).limit(3).all()

    if recent_sprints:
        sprint_ids = [s.id for s in recent_sprints]
        completed_pts_list = []
        for sid in sprint_ids:
            pts = db.query(JiraTicket).filter(
                JiraTicket.org_id == org_id,
                JiraTicket.sprint_id == sid,
                JiraTicket.status.in_(["Done", "Closed", "Resolved"]),
                JiraTicket.is_deleted == False,
            ).all()
            completed_pts_list.append(sum(t.story_points or 0 for t in pts))
        avg_velocity = int(sum(completed_pts_list) / len(completed_pts_list)) if completed_pts_list else 40
    else:
        avg_velocity = 40

    backlog_ctx = "\n".join(
        f"- {t.jira_key} | {t.priority or 'Medium'} | SP:{t.story_points or '?'} | {(t.summary or '')[:70]}"
        for t in backlog[:20]
    )

    prompt = f"""Pod: {pod}. Health: {health['health_score']}/100. Blockers: {health['risk_flags']['blocked']}. Velocity score: {health['radar']['velocity']}%.
Historical avg velocity: {avg_velocity} story points per sprint.

Available backlog tickets (you MUST only use keys from this list — do NOT invent keys):
{backlog_ctx}

Select 8-10 tickets that fit within {avg_velocity} story points total.
Prioritise: bug fixes first, then high-priority features, then tech debt.
Return ONLY a JSON array — no prose, no explanation:
[{{
  "key": "EXACT-KEY-FROM-LIST-ABOVE",
  "suggested_points": 3,
  "rationale": "one sentence why"
}}]"""

    try:
        raw = await asyncio.wait_for(
            chat(user_message=prompt, temperature=0, max_tokens=600),
            timeout=20.0,
        )
        ai_tickets = _parse_nova_json(raw)
        if isinstance(ai_tickets, list):
            # Validate and enrich every AI ticket against real DB records
            validated = []
            for item in ai_tickets:
                key = item.get("key", "")
                db_ticket = backlog_lookup.get(key)
                if db_ticket is None:
                    continue  # AI hallucinated a key — discard
                validated.append({
                    "key":              db_ticket.jira_key,
                    "summary":          db_ticket.summary,          # always use real summary
                    "priority":         db_ticket.priority or "Medium",  # always use real priority
                    "suggested_points": item.get("suggested_points") or db_ticket.story_points or 3,
                    "rationale":        item.get("rationale", "Selected by EOS."),
                })
            if validated:
                total_pts = sum(t["suggested_points"] for t in validated)
                return {
                    "pod":          pod,
                    "tickets":      validated,
                    "total_points": total_pts,
                    "rationale":    f"EOS selected {len(validated)} tickets ({total_pts} pts) targeting {avg_velocity}-point capacity.",
                    "nova_powered": True,
                }
    except Exception:
        pass

    # Deterministic fallback: top tickets by priority order
    PRIORITY_ORDER = {"critical": 0, "blocker": 0, "highest": 0, "high": 1, "medium": 2, "low": 3}
    sorted_backlog = sorted(
        backlog,
        key=lambda t: (PRIORITY_ORDER.get((t.priority or "medium").lower(), 2), -(t.story_points or 0)),
    )
    fallback_tickets = [
        {
            "key":              t.jira_key,
            "summary":          t.summary,
            "suggested_points": t.story_points or 3,
            "priority":         t.priority or "Medium",
            "rationale":        f"Selected by priority ({t.priority or 'Medium'}) from backlog.",
        }
        for t in sorted_backlog[:8]
    ]
    total_pts = sum(t["suggested_points"] for t in fallback_tickets)
    return {
        "pod":          pod,
        "tickets":      fallback_tickets,
        "total_points": total_pts,
        "rationale":    "Sorted by priority — NOVA unavailable.",
        "nova_powered": False,
    }


@router.post("/knowledge-gaps/detect")
async def trigger_gap_detection(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_manager_up),
):
    """Manually trigger knowledge gap detection for the org."""
    from app.ai.knowledge_gaps import detect_knowledge_gaps

    gaps = await detect_knowledge_gaps(user.org_id, db)
    return {"detected": len(gaps), "gaps": gaps}


@router.post("/goals-insight")
async def goals_insight(
    body: dict,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Generate a NOVA AI insight for a specific goal.
    Caches result so repeated refreshes are deterministic."""
    from app.ai.nova import chat
    from app.models.goal import Goal
    from app.models.ticket import JiraTicket
    from app.models.sprint import Sprint

    goal_id = body.get("goal_id")
    if not goal_id:
        raise HTTPException(400, "goal_id is required")

    goal = db.query(Goal).filter(
        Goal.id == goal_id,
        Goal.org_id == user.org_id,
    ).first()
    if not goal:
        raise HTTPException(404, "Goal not found")

    # Gather linked ticket context
    kr_titles = []
    all_linked_keys = set()
    for kr in (goal.key_results or []):
        kr_titles.append(kr.get("title", ""))
        all_linked_keys.update(kr.get("linked_tickets", []))

    tickets_ctx = ""
    if all_linked_keys:
        tickets = db.query(JiraTicket).filter(
            JiraTicket.jira_key.in_(list(all_linked_keys)),
            JiraTicket.org_id == user.org_id,
            JiraTicket.is_deleted == False,
        ).all()
        ticket_lines = []
        for t in tickets:
            line = f"- {t.jira_key} | {t.status} | {t.priority or 'Medium'} | {(t.summary or '')[:60]}"
            ticket_lines.append(line)
        tickets_ctx = "\n".join(ticket_lines) or "No linked tickets found."
    else:
        tickets_ctx = "No linked tickets."

    # Sprint context
    sprint_ctx = ""
    if goal.linked_sprints:
        sprints = db.query(Sprint).filter(
            Sprint.name.in_(goal.linked_sprints),
            Sprint.org_id == user.org_id,
        ).all()
        if sprints:
            sp = sprints[0]
            sprint_ctx = f"Linked sprint: {sp.name} ({sp.status})."

    # ── Cache check ──
    data_hash = _compute_data_hash(
        goal.title, goal.description, goal.status, goal.overall_progress,
        goal.key_results, goal.linked_sprints,
        tickets_ctx, sprint_ctx,
    )
    if goal.nova_insight and goal.nova_insight_hash == data_hash:
        return {"insight": goal.nova_insight}

    prompt = f"""Goal: {goal.title}
Description: {goal.description or 'N/A'}
Status: {goal.status}
Progress: {goal.overall_progress}%

Key Results:
"""
    for kr in (goal.key_results or []):
        prompt += f"- {kr.get('title', '')}: {kr.get('current', 0)}/{kr.get('target', 1)} {kr.get('unit', '')} ({kr.get('status', 'on_track')})\n"

    prompt += f"""
Linked Tickets:
{tickets_ctx}

{sprint_ctx}

Write a concise, actionable AI insight (2-3 sentences) for this OKR.
Be specific about risks, blockers, or next steps.
If the goal is on track, say so and mention what completes it.
If at risk or behind, flag the critical path and suggest one concrete action."""

    try:
        insight = await chat(
            user_message=prompt,
            temperature=0,
            max_tokens=200,
        )
    except Exception:
        # Fallback insight
        if goal.status == "on_track":
            insight = f"{goal.title} is progressing well at {goal.overall_progress}%. Continue current momentum to close remaining key results."
        elif goal.status == "complete":
            insight = f"{goal.title} has been achieved. Document learnings and celebrate the win with the team."
        elif goal.status == "at_risk":
            insight = f"{goal.title} is at risk at {goal.overall_progress}%. Review blocked linked tickets and consider reallocating capacity."
        else:
            insight = f"{goal.title} is behind at {goal.overall_progress}%. Immediate scope reduction or additional resources are recommended."

    # Persist cache
    goal.nova_insight = insight
    goal.nova_insight_hash = data_hash
    db.commit()


# ── EOS Intelligence Endpoints ────────────────────────────────────────────────

@router.get("/cognitive-load")
async def cognitive_load(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Cognitive load score per team member based on WIP, priority, and overdue factors."""
    from app.models.ticket import JiraTicket
    from app.ai.nova import chat
    from datetime import date

    org_id = user.org_id
    today  = date.today()
    DONE   = {"Done", "Closed", "Resolved"}

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id     == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.assignee   != None,
        JiraTicket.status.notin_(list(DONE)),
    ).all()

    assignee_stats: dict = {}
    for t in tickets:
        a = t.assignee
        if a not in assignee_stats:
            assignee_stats[a] = {"wip": 0, "high_priority": 0, "overdue": 0, "pts": 0}
        assignee_stats[a]["wip"]          += 1
        assignee_stats[a]["pts"]          += t.story_points or 0
        if (t.priority or "") in ("High", "Highest"):
            assignee_stats[a]["high_priority"] += 1
        if t.due_date and t.due_date < today:
            assignee_stats[a]["overdue"]   += 1

    members = []
    for name, s in assignee_stats.items():
        raw   = s["wip"] * 10 + s["high_priority"] * 15 + s["overdue"] * 20
        score = min(100, raw)
        level = ("Overloaded" if score >= 70
                 else "High"       if score >= 50
                 else "Moderate"   if score >= 30
                 else "Optimal")
        members.append({
            "name":                name,
            "load_score":          score,
            "level":               level,
            "wip_count":           s["wip"],
            "high_priority_count": s["high_priority"],
            "overdue_count":       s["overdue"],
            "story_points":        s["pts"],
        })
    members.sort(key=lambda x: x["load_score"], reverse=True)

    ai_summary = "No active assignments found."
    if members:
        lines = "; ".join(
            f"{m['name']}: load={m['load_score']} ({m['level']}), WIP={m['wip_count']}, overdue={m['overdue_count']}"
            for m in members[:8]
        )
        prompt = (
            f"You are EOS, an engineering team coach. Analyse cognitive load distribution.\n"
            f"Team data: {lines}\n"
            f"In 2 concise sentences: (1) overall pattern, "
            f"(2) one specific recommendation for the highest-loaded member. Be direct."
        )
        try:
            ai_summary = await chat(user_message=prompt, max_tokens=150)
        except Exception:
            ai_summary = f"{members[0]['name']} is at {members[0]['level']} cognitive load with {members[0]['wip_count']} open tickets. Consider redistributing high-priority tasks."

    return {"members": members, "ai_summary": ai_summary, "total_members": len(members)}


@router.get("/team-chemistry")
async def team_chemistry(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Team chemistry: workload balance per pod with AI collaboration analysis."""
    from app.models.ticket import JiraTicket
    from app.ai.nova import chat

    org_id = user.org_id

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id     == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.assignee   != None,
        JiraTicket.pod        != None,
    ).all()

    pod_pts: dict = {}
    for t in tickets:
        pod = (t.pod or "").strip()
        if not pod:
            continue
        if pod not in pod_pts:
            pod_pts[pod] = {}
        a = t.assignee
        pod_pts[pod][a] = pod_pts[pod].get(a, 0) + (t.story_points or 0)

    balance_data = []
    for pod, member_pts in pod_pts.items():
        vals = list(member_pts.values())
        if len(vals) < 2:
            continue
        avg = sum(vals) / len(vals)
        std = (sum((v - avg) ** 2 for v in vals) / len(vals)) ** 0.5
        cv  = round((std / max(avg, 1)) * 100)
        balance_data.append({
            "pod":           pod,
            "members":       len(vals),
            "avg_pts":       round(avg, 1),
            "imbalance_pct": cv,
            "most_loaded":   max(member_pts, key=member_pts.get),
            "least_loaded":  min(member_pts, key=member_pts.get),
        })
    balance_data.sort(key=lambda x: x["imbalance_pct"], reverse=True)

    pod_summary = "; ".join(
        f"{p['pod']}: {p['members']} members, imbalance={p['imbalance_pct']}%, top={p['most_loaded']}"
        for p in balance_data[:5]
    )

    ai_analysis = "Not enough pod data to analyse team chemistry."
    if balance_data:
        prompt = (
            f"You are EOS, an engineering team dynamics analyst.\n"
            f"Pod workload balance: {pod_summary}\n"
            f"Write 3 concise bullet points:\n"
            f"• Overall cohesion pattern (silos vs collaboration)\n"
            f"• Worst imbalance and why it matters\n"
            f"• One specific recommendation to improve team chemistry\nBe direct."
        )
        try:
            ai_analysis = await chat(user_message=prompt, max_tokens=200)
        except Exception:
            worst = balance_data[0]
            ai_analysis = (
                f"• {worst['pod']} shows the highest workload imbalance at {worst['imbalance_pct']}%.\n"
                f"• {worst['most_loaded']} carries a disproportionate share — risk of burnout.\n"
                f"• Redistribute 2-3 tickets from {worst['most_loaded']} to {worst['least_loaded']} this sprint."
            )

    return {"pod_balance": balance_data, "ai_analysis": ai_analysis, "pod_count": len(balance_data)}


@router.get("/memory-graph")
async def memory_graph(
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
):
    """Institutional memory map: who knows what, based on ticket history, plus bus factor risks."""
    from app.models.ticket import JiraTicket
    from app.ai.nova import chat

    org_id = user.org_id

    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id     == org_id,
        JiraTicket.is_deleted == False,
        JiraTicket.assignee   != None,
    ).all()

    member_data: dict    = {}
    pod_contributors: dict = {}

    for t in tickets:
        a   = t.assignee
        pod = (t.pod or "Unknown").strip()

        if a not in member_data:
            member_data[a] = {"pods": set(), "types": set(), "count": 0}
        member_data[a]["pods"].add(pod)
        if t.issue_type:
            member_data[a]["types"].add(t.issue_type)
        member_data[a]["count"] += 1

        if pod not in pod_contributors:
            pod_contributors[pod] = set()
        pod_contributors[pod].add(a)

    expertise_map = sorted(
        [
            {
                "name":              name,
                "pods":              sorted(d["pods"]),
                "ticket_count":      d["count"],
                "specializations":   sorted(d["types"]),
                "knowledge_breadth": len(d["pods"]),
            }
            for name, d in member_data.items()
        ],
        key=lambda x: x["ticket_count"],
        reverse=True,
    )

    bus_factor_risks = [
        {
            "pod":          pod,
            "contributors": len(members),
            "risk":         "High"   if len(members) == 1
                            else "Medium" if len(members) == 2
                            else "Low",
        }
        for pod, members in pod_contributors.items()
        if len(members) <= 2
    ]

    top_experts = "; ".join(
        f"{m['name']}: {m['ticket_count']} tickets across {', '.join(m['pods'][:3])}"
        for m in expertise_map[:5]
    )
    high_risk = "; ".join(r["pod"] for r in bus_factor_risks if r["risk"] == "High")

    ai_summary = "No ticket assignment data found."
    if expertise_map:
        prompt = (
            f"You are EOS, an institutional knowledge analyst.\n"
            f"Top contributors: {top_experts or 'No data.'}\n"
            f"Bus factor risks (pods with 1 contributor): {high_risk or 'None.'}\n"
            f"In 2 sentences: (1) highest institutional knowledge risk, "
            f"(2) one specific knowledge transfer recommendation."
        )
        try:
            ai_summary = await chat(user_message=prompt, max_tokens=150)
        except Exception:
            ai_summary = (
                f"Single-contributor pods ({high_risk or 'none'}) represent the highest bus-factor risk. "
                f"Schedule pair-programming sessions with {expertise_map[0]['name']} to distribute critical knowledge."
            )

    return {
        "expertise_map":    expertise_map[:10],
        "bus_factor_risks": bus_factor_risks,
        "ai_summary":       ai_summary,
    }

    return {"insight": insight}


# ── Media-to-Ticket Endpoints ─────────────────────────────────────────────────

class ImageAnalyzeRequest(BaseModel):
    image:       str   # base64-encoded image (no data URI prefix)
    description: str = ""


@router.post("/analyze-image")
async def analyze_image(
    body: ImageAnalyzeRequest,
    user: User = Depends(get_current_user),
):
    """
    Analyze a screenshot using the llava vision model (Ollama).
    Returns structured bug fields ready for ticket creation.
    Requires: ollama pull llava
    """
    from app.ai.nova import analyze_image_with_llava
    try:
        result = await analyze_image_with_llava(body.image, body.description)
        return result
    except Exception as e:
        raise HTTPException(503, f"Vision analysis unavailable: {e}")


@router.post("/transcribe")
async def transcribe_media(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """
    Transcribe an audio or video file using faster-whisper (local, no API key).
    Then runs the transcript through the ticket intelligence pipeline.
    Returns: {transcript, fields: {title, description, priority, issue_type, ...}}
    Supports: mp3, wav, m4a, mp4, mov, avi, mkv, webm
    """
    from app.ai.media import process_media_file
    from app.ai.ticket_intelligence import analyse_ticket

    allowed_types = {
        "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/x-m4a",
        "audio/ogg", "video/mp4", "video/quicktime", "video/x-msvideo",
        "video/x-matroska", "video/webm",
    }
    ct = file.content_type or ""
    filename = file.filename or "upload"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_exts = {"mp3", "wav", "m4a", "ogg", "mp4", "mov", "avi", "mkv", "webm"}

    if ct not in allowed_types and ext not in allowed_exts:
        raise HTTPException(400, f"Unsupported file type: {ct or ext}. Use audio or video files.")

    max_bytes = 100 * 1024 * 1024  # 100 MB
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(413, "File too large (max 100 MB)")

    try:
        media_result = await process_media_file(content, filename)
        transcript   = media_result["transcript"]

        if not transcript.strip():
            raise HTTPException(422, "Could not extract speech from the file. Check that it contains clear audio.")

        # Run ticket intelligence on the transcript
        fields = await analyse_ticket(transcript, available_users=[])

        return {
            "transcript": transcript,
            "fields":     fields,
            "source":     filename,
        }
    except HTTPException:
        raise
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {e}")
