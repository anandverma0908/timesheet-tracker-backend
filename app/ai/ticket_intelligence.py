"""NOVA Ticket Intelligence — agentic flow for smart ticket creation."""
import json
import asyncio
from app.ai.nova import chat, embed
from app.ai.search import find_similar_tickets

TICKET_CLASSIFY_PROMPT = """Analyse this ticket and extract structured information.
Return ONLY valid JSON, no other text.

Ticket: {text}

Return JSON with these exact fields:
{{
  "title": "concise ticket title (max 100 chars)",
  "description": "expanded description with more detail",
  "issue_type": "Bug|Story|Task|Epic",
  "priority": "Critical|High|Medium|Low",
  "pod": "one of: DPAI, EDM, SNOP, SNOE, PA, IAM, PLAT, SNPRM, TMSNG",
  "client": "client name or null",
  "story_points": 1,
  "labels": ["label1"],
  "suggested_assignee_role": "SDE1|SDE2|SDE3|SDET|BA",
  "confidence": 0.0,
  "reasoning": "brief explanation"
}}"""


async def analyse_ticket(text: str) -> dict:
    """Step 1 — extract structured fields from NL text via NOVA."""
    try:
        raw   = await chat(TICKET_CLASSIFY_PROMPT.format(text=text), temperature=0.1, max_tokens=500)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        return json.loads(raw[start:end])
    except Exception as e:
        return {"error": str(e), "title": text[:100]}


async def full_analysis(nl_text: str, org_id: str) -> dict:
    """Full agentic pipeline: classify + duplicate check in parallel."""
    init_embed  = embed(nl_text)
    fields_task = analyse_ticket(nl_text)
    dupes_task  = find_similar_tickets(init_embed, org_id, threshold=0.85, limit=3)
    fields, dupes = await asyncio.gather(fields_task, dupes_task)
    return {
        "fields":         fields,
        "duplicates":     dupes,
        "has_duplicates": len(dupes) > 0,
    }
