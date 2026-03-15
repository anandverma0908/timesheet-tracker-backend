"""
sync.py — Syncs Jira tickets + worklogs into PostgreSQL.

Strategy:
  - Upsert tickets by (org_id, jira_key) — insert or update
  - Delete + recreate worklogs for each ticket (simplest, worklogs are small)
  - Log every sync run in sync_log table
"""

import os
from datetime import datetime, date
from typing import Optional
from sqlalchemy.orm import Session

from database import (
    SessionLocal, Organisation, JiraTicket, Worklog, SyncLog, gen_uuid
)
from jira_client import JiraClient


def _parse_date(val) -> Optional[date]:
    if not val:
        return None
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def sync_org(org: Organisation, db: Session) -> SyncLog:
    """
    Full sync for one organisation.
    Returns the SyncLog row.
    """
    log = SyncLog(
        id         = gen_uuid(),
        org_id     = org.id,
        started_at = datetime.utcnow(),
        status     = "running",
    )
    db.add(log)
    db.commit()

    print(f"\n🔄 Starting sync for org: {org.name}")

    try:
        client = JiraClient(
            base_url    = org.jira_url,
            email       = org.jira_email,
            api_token   = org.jira_api_token,
            project_key = org.jira_project_key or None,
        )
        # Override custom field IDs from org config
        client.CLIENT_FIELD = org.jira_client_field
        client.POD_FIELD    = org.jira_pod_field

        tickets = client.fetch_tickets()

        tickets_synced  = 0
        worklogs_synced = 0

        for t in tickets:
            # ── Upsert ticket ──
            existing = (
                db.query(JiraTicket)
                .filter(JiraTicket.org_id == org.id, JiraTicket.jira_key == t["key"])
                .first()
            )

            if existing:
                row = existing
            else:
                row = JiraTicket(id=gen_uuid(), org_id=org.id, jira_key=t["key"])
                db.add(row)

            row.project_key              = t["project_key"]
            row.project_name             = t.get("project_name")
            row.summary                  = t["summary"]
            row.assignee                 = t.get("assignee")
            row.assignee_email           = t.get("assignee_email")
            row.status                   = t.get("status")
            row.client                   = t.get("client")
            row.pod                      = t.get("pod")
            row.issue_type               = t.get("issue_type")
            row.priority                 = t.get("priority")
            row.hours_spent              = t.get("hours_spent", 0)
            row.original_estimate_hours  = t.get("original_estimate_hours", 0)
            row.remaining_estimate_hours = t.get("remaining_estimate_hours", 0)
            row.jira_created             = _parse_date(t.get("created"))
            row.jira_updated             = _parse_date(t.get("updated"))
            row.url                      = t.get("url")
            row.synced_at                = datetime.utcnow()

            db.flush()  # get the row.id before inserting worklogs

            # ── Replace worklogs ──
            db.query(Worklog).filter(Worklog.ticket_id == row.id).delete()

            for w in t.get("worklogs", []):
                wl = Worklog(
                    id           = gen_uuid(),
                    ticket_id    = row.id,
                    author       = w.get("author"),
                    author_email = w.get("email"),
                    log_date     = _parse_date(w.get("date")),
                    hours        = w.get("hours", 0),
                    comment      = w.get("comment"),
                )
                db.add(wl)
                worklogs_synced += 1

            tickets_synced += 1

        db.commit()

        log.finished_at     = datetime.utcnow()
        log.status          = "success"
        log.tickets_synced  = tickets_synced
        log.worklogs_synced = worklogs_synced
        db.commit()

        print(f"✅ Sync complete: {tickets_synced} tickets, {worklogs_synced} worklogs")

    except Exception as e:
        db.rollback()
        log.finished_at = datetime.utcnow()
        log.status      = "failed"
        log.error       = str(e)
        db.commit()
        print(f"❌ Sync failed: {e}")

    return log


def sync_all_orgs() -> None:
    """Called by the background scheduler every N minutes."""
    db = SessionLocal()
    try:
        orgs = db.query(Organisation).all()
        print(f"\n⏰ Scheduled sync — {len(orgs)} org(s)")
        for org in orgs:
            sync_org(org, db)
    finally:
        db.close()


def get_last_sync(org_id: str, db: Session) -> Optional[SyncLog]:
    return (
        db.query(SyncLog)
        .filter(SyncLog.org_id == org_id)
        .order_by(SyncLog.started_at.desc())
        .first()
    )