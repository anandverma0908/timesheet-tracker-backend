"""
app/services/webhook_service.py — Dispatches event notifications to Slack/Teams/webhooks.
"""

import logging
import httpx
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EVENT_LABELS = {
    "ticket_created":   "Ticket Created",
    "status_changed":   "Status Changed",
    "sprint_started":   "Sprint Started",
    "sprint_completed": "Sprint Completed",
    "mention":          "Mention",
    "comment_added":    "Comment Added",
}


def _slack_payload(event_type: str, data: dict) -> dict:
    """Build a Slack-compatible message payload."""
    label = EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())

    text = data.get("message") or f"*{label}*"
    fields = []

    if data.get("ticket_key"):
        fields.append({"type": "mrkdwn", "text": f"*Ticket:*\n{data['ticket_key']}"})
    if data.get("summary"):
        fields.append({"type": "mrkdwn", "text": f"*Summary:*\n{data['summary']}"})
    if data.get("old_status") and data.get("new_status"):
        fields.append({"type": "mrkdwn", "text": f"*Status:*\n{data['old_status']} → {data['new_status']}"})
    if data.get("assignee"):
        fields.append({"type": "mrkdwn", "text": f"*Assignee:*\n{data['assignee']}"})
    if data.get("user"):
        fields.append({"type": "mrkdwn", "text": f"*By:*\n{data['user']}"})

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":bell: *{label}*"},
        }
    ]
    if fields:
        blocks.append({"type": "section", "fields": fields[:10]})
    if data.get("link"):
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View Ticket"},
                "url": data["link"],
            }],
        })

    return {"text": text, "blocks": blocks}


def _teams_payload(event_type: str, data: dict) -> dict:
    """Build a Teams-compatible Adaptive Card payload."""
    label = EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())

    facts = []
    if data.get("ticket_key"):
        facts.append({"title": "Ticket", "value": data["ticket_key"]})
    if data.get("summary"):
        facts.append({"title": "Summary", "value": str(data["summary"])[:200]})
    if data.get("old_status") and data.get("new_status"):
        facts.append({"title": "Status", "value": f"{data['old_status']} → {data['new_status']}"})
    if data.get("assignee"):
        facts.append({"title": "Assignee", "value": data["assignee"]})
    if data.get("user"):
        facts.append({"title": "By", "value": data["user"]})

    body = [
        {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": f"🔔 {label}"},
        {"type": "FactSet", "facts": facts},
    ]

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body,
            },
        }],
    }


async def dispatch_event(
    org_id: str,
    event_type: str,
    data: dict,
    db: Session,
) -> int:
    """
    Find active integrations for org that subscribe to event_type and POST to their webhooks.
    Returns the number of webhooks successfully dispatched.
    """
    from app.models.integration import Integration

    integrations = db.query(Integration).filter(
        Integration.org_id == org_id,
        Integration.is_active == True,
    ).all()

    matched = [i for i in integrations if event_type in (i.events or [])]
    logger.info(f"[webhook] dispatch_event: event={event_type} org={org_id} total_integrations={len(integrations)} matched={len(matched)}")
    if not matched:
        return 0

    sent = 0
    async with httpx.AsyncClient(timeout=5.0) as client:
        for integration in matched:
            try:
                if integration.type == "slack":
                    payload = _slack_payload(event_type, data)
                elif integration.type == "teams":
                    payload = _teams_payload(event_type, data)
                else:
                    payload = {"event": event_type, "data": data}

                resp = await client.post(integration.webhook_url, json=payload)
                if resp.status_code < 300:
                    sent += 1
                else:
                    logger.warning(f"Webhook {integration.id} returned {resp.status_code}")
            except Exception as e:
                logger.warning(f"Webhook dispatch failed for integration {integration.id}: {e}")

    return sent


async def test_webhook(webhook_url: str, integration_type: str) -> bool:
    """Send a test ping to a webhook URL. Returns True on success."""
    data = {
        "message": "Test connection from Trackly",
        "ticket_key": "TRK-1",
        "summary": "This is a test notification from your Trackly integration.",
        "user": "Trackly",
    }
    try:
        if integration_type == "slack":
            payload = _slack_payload("ticket_created", data)
        elif integration_type == "teams":
            payload = _teams_payload("ticket_created", data)
        else:
            payload = {"event": "test", "data": data}

        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(webhook_url, json=payload)
            return resp.status_code < 300
    except Exception as e:
        logger.warning(f"Test webhook failed: {e}")
        return False
