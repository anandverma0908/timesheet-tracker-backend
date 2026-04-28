"""NOVA Ticket Intelligence — agentic flow for smart ticket creation."""
import json
import asyncio
from app.ai.nova import chat, embed
from app.ai.search import find_similar_tickets

TICKET_CLASSIFY_PROMPT = """Analyse this ticket and extract structured information.
Return ONLY valid JSON, no other text.

Ticket: {text}
{user_hint}
Return JSON with these exact fields:
{{
  "title": "concise ticket title (max 100 chars)",
  "description": "expanded description with more detail",
  "issue_type": "Bug|Story|Task|Epic|Subtask|Improvement",
  "priority": "Highest|High|Medium|Low|Lowest",
  "pod": "one of: DPAI, EDM, SNOP, SNOE, PA, IAM, PLAT, SNPRM, TMSNG",
  "client": "client name or null",
  "story_points": 1,
  "labels": ["label1"],
  "assignee": "exact name from the available team members list that best fits this ticket, or null",
  "confidence": 0.85,
  "reasoning": "brief explanation"
}}"""


async def analyse_ticket(text: str, available_users: list = []) -> dict:
    """Step 1 — extract structured fields from NL text via NOVA."""
    try:
        user_hint = (
            f"Available team members (pick the best fit for 'assignee'): {', '.join(available_users)}"
            if available_users else ""
        )
        prompt = TICKET_CLASSIFY_PROMPT.format(text=text, user_hint=user_hint)
        raw   = await chat(prompt, temperature=0, max_tokens=500)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except Exception as e:
        return {"error": str(e), "title": text[:100]}


async def full_analysis(nl_text: str, org_id: str, available_users: list = []) -> dict:
    """Full agentic pipeline: classify + duplicate check in parallel."""
    init_embed  = embed(nl_text)
    fields_task = analyse_ticket(nl_text, available_users)
    dupes_task  = find_similar_tickets(init_embed, org_id, threshold=0.72, limit=3, query_text=nl_text)
    fields, dupes = await asyncio.gather(fields_task, dupes_task)
    return {
        "fields":         fields,
        "duplicates":     dupes,
        "has_duplicates": len(dupes) > 0,
        "confidence":     fields.get("confidence") if isinstance(fields.get("confidence"), (int, float)) else None,
    }
