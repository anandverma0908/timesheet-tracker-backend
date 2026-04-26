"""Nova AI — test case generation and coverage analysis."""
import json
import logging
from typing import Optional
from app.ai.nova import chat

logger = logging.getLogger(__name__)

GENERATE_PROMPT = """You are a senior QA engineer. Generate {count} test cases for the following ticket.

Ticket Key: {key}
Summary: {summary}
Description: {description}

Return ONLY valid JSON array, no other text. Each item must have:
{{
  "title": "short test case title",
  "description": "what this test verifies",
  "preconditions": "setup needed before the test (or null)",
  "steps": [
    {{"step": "action to perform", "expected_result": "what should happen"}},
    ...
  ],
  "priority": "high|medium|low"
}}

Cover: happy path, edge cases, negative scenarios, and boundary conditions. Be specific to the ticket."""

COVERAGE_PROMPT = """You are a QA lead reviewing test coverage for a software team.

Pod/Project: {pod}
Total tickets in active sprint: {total}
Tickets with test cases: {tested}
Untested tickets: {untested_list}

Write a 2-sentence insight about the current test coverage and what the team should prioritise.
Be direct and specific. No fluff."""


async def generate_test_cases(
    ticket_key: str,
    ticket_summary: str,
    ticket_description: Optional[str],
    count: int = 5,
) -> list[dict]:
    try:
        prompt = GENERATE_PROMPT.format(
            count=count,
            key=ticket_key,
            summary=ticket_summary,
            description=ticket_description or "No description provided.",
        )
        raw = await chat(prompt, temperature=0.3, max_tokens=2000)
        start = raw.find("[")
        end = raw.rfind("]") + 1
        if start == -1 or end == 0:
            logger.warning("Nova returned no JSON array for test generation")
            return []
        return json.loads(raw[start:end])
    except Exception as e:
        logger.error(f"Test generation failed: {e}")
        return []


async def generate_coverage_insight(
    pod: str,
    total: int,
    tested: int,
    untested_summaries: list[str],
) -> str:
    try:
        untested_list = "\n".join(f"- {s}" for s in untested_summaries[:10]) or "none"
        prompt = COVERAGE_PROMPT.format(
            pod=pod,
            total=total,
            tested=tested,
            untested_list=untested_list,
        )
        return await chat(prompt, temperature=0.2, max_tokens=200)
    except Exception as e:
        logger.error(f"Coverage insight failed: {e}")
        return f"{tested}/{total} tickets have test coverage."
