"""
app/services/automation_engine.py — Workflow automation engine.

Triggered by ticket/sprint events. Loads active rules, checks conditions, executes actions.
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.models.ticket import JiraTicket
from app.models.audit import AuditLog
from app.models.base import gen_uuid

logger = logging.getLogger(__name__)

TRIGGER_TYPES = [
    "status_change",
    "ticket_created",
    "ticket_assigned",
    "sprint_started",
    "sprint_completed",
    "due_date_reached",
]

ACTION_TYPES = [
    "set_status",
    "assign_to",
    "set_priority",
    "add_label",
    "post_comment",
    "create_subtask",
    "notify_slack",
]


async def run_automations(
    trigger_type: str,
    trigger_data: dict,
    org_id: str,
    pod: str,
    db: Session,
) -> int:
    """
    Load active automation rules matching trigger_type + pod, evaluate conditions,
    execute actions. Returns number of rules that fired.
    """
    rules = db.query(AutomationRule).filter(
        AutomationRule.org_id == org_id,
        AutomationRule.pod == pod,
        AutomationRule.is_active == True,
        AutomationRule.trigger_type == trigger_type,
    ).all()

    fired = 0
    for rule in rules:
        try:
            if _check_condition(rule, trigger_data, db):
                await _execute_action(rule, trigger_data, org_id, db)
                rule.run_count = (rule.run_count or 0) + 1
                fired += 1
        except Exception as e:
            logger.warning(f"Automation rule {rule.id} failed: {e}")

    if fired > 0:
        db.commit()
    return fired


def _check_condition(rule: AutomationRule, trigger_data: dict, db: Session) -> bool:
    """Evaluate the rule's condition against trigger data."""
    if not rule.condition_type or rule.condition_type == "always":
        return True

    cond = rule.condition_config or {}
    ticket = _get_ticket(trigger_data, db)
    if not ticket:
        return False

    if rule.condition_type == "priority_is":
        return (ticket.priority or "").lower() == (cond.get("priority") or "").lower()
    if rule.condition_type == "assignee_is":
        return (ticket.assignee or "").lower() == (cond.get("assignee") or "").lower()
    if rule.condition_type == "issue_type_is":
        return (ticket.issue_type or "").lower() == (cond.get("issue_type") or "").lower()
    if rule.condition_type == "status_is":
        return (ticket.status or "").lower() == (cond.get("status") or "").lower()

    return False


async def _execute_action(rule: AutomationRule, trigger_data: dict, org_id: str, db: Session) -> None:
    """Execute the rule's action."""
    action = rule.action_config or {}
    ticket = _get_ticket(trigger_data, db)

    if rule.action_type == "set_status":
        if ticket:
            old = ticket.status
            ticket.status = action.get("status")
            _log_audit(db, ticket.id, org_id, rule.created_by, "automation_status", {"old": old, "new": ticket.status})

    elif rule.action_type == "assign_to":
        if ticket:
            ticket.assignee = action.get("user_id")
            _log_audit(db, ticket.id, org_id, rule.created_by, "automation_assign", {"assignee": ticket.assignee})

    elif rule.action_type == "set_priority":
        if ticket:
            ticket.priority = action.get("priority")
            _log_audit(db, ticket.id, org_id, rule.created_by, "automation_priority", {"priority": ticket.priority})

    elif rule.action_type == "add_label":
        if ticket:
            label = action.get("label")
            existing = set(ticket.labels or [])
            existing.add(label)
            ticket.labels = list(existing)
            _log_audit(db, ticket.id, org_id, rule.created_by, "automation_label", {"label": label})

    elif rule.action_type == "post_comment":
        if ticket:
            from app.models.ticket import TicketComment
            db.add(TicketComment(
                id=gen_uuid(),
                ticket_id=ticket.id,
                author_id=rule.created_by,
                body=action.get("comment_body", "Automated comment"),
            ))
            _log_audit(db, ticket.id, org_id, rule.created_by, "automation_comment", {"body": action.get("comment_body", "")[:100]})

    elif rule.action_type == "create_subtask":
        if ticket:
            from app.models.ticket import JiraTicket as JT
            sub = JT(
                id=gen_uuid(),
                org_id=org_id,
                jira_key=_next_key(db, org_id),
                project_key=ticket.project_key,
                summary=action.get("subtask_summary", "Sub-task"),
                issue_type="Subtask",
                priority=ticket.priority,
                status="To Do",
                pod=ticket.pod,
                parent_id=ticket.id,
                is_deleted=False,
            )
            db.add(sub)
            _log_audit(db, ticket.id, org_id, rule.created_by, "automation_subtask", {"child_key": sub.jira_key})

    elif rule.action_type == "notify_slack":
        webhook_url = action.get("webhook_url")
        if webhook_url:
            from app.services.webhook_service import _slack_payload
            import httpx
            payload_data = {
                "ticket_key": trigger_data.get("ticket_key", ""),
                "summary": ticket.summary if ticket else "",
                "message": action.get("message", f"Automation triggered: {rule.name}"),
                "old_status": trigger_data.get("old_status"),
                "new_status": trigger_data.get("new_status"),
            }
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    await client.post(webhook_url, json=_slack_payload("automation", payload_data))
            except Exception as e:
                logger.warning(f"notify_slack action failed: {e}")


def _get_ticket(trigger_data: dict, db: Session) -> Optional[JiraTicket]:
    tid = trigger_data.get("ticket_id")
    if tid:
        return db.query(JiraTicket).filter(JiraTicket.id == tid).first()
    tkey = trigger_data.get("ticket_key")
    if tkey:
        return db.query(JiraTicket).filter(JiraTicket.jira_key == tkey).first()
    return None


def _log_audit(db: Session, entity_id: str, org_id: str, user_id: Optional[str], action: str, diff: dict) -> None:
    db.add(AuditLog(
        id=gen_uuid(),
        entity_type="ticket",
        entity_id=entity_id,
        user_id=user_id,
        org_id=org_id,
        action=action,
        diff_json=diff,
    ))


def _next_key(db: Session, org_id: str) -> str:
    from sqlalchemy import text
    result = db.execute(text("SELECT COUNT(*) FROM jira_tickets WHERE org_id = :oid"), {"oid": org_id}).scalar()
    return f"TRKLY-{(result or 0) + 1}"
