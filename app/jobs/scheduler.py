"""
app/jobs/scheduler.py — APScheduler setup for background jobs.

Jobs:
  - jira_sync:   sync Jira tickets for all orgs (every N minutes)
  - standup_job: generate AI standups for all users (9AM daily Mon–Fri)
  - burnrate_job: check client burn rates and fire alerts (hourly)
  - gaps_job:    detect knowledge gaps (weekly Monday 8AM)

Register via start_scheduler() in app lifespan.
"""

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.config import settings

logger    = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


# ── Jobs ───────────────────────────────────────────────────────────────────

async def _jira_sync_job():
    """Sync Jira tickets for every organisation that has credentials configured."""
    try:
        from app.core.database import SessionLocal
        from app.models.organisation import Organisation

        db   = SessionLocal()
        orgs = db.query(Organisation).filter(
            Organisation.jira_url   != None,
            Organisation.jira_token != None,
        ).all()
        db.close()

        for org in orgs:
            try:
                from sync import sync_org
                sync_org(org, db)
                logger.info(f"Jira sync complete for org {org.id}")
            except Exception as e:
                logger.warning(f"Jira sync failed for org {org.id}: {e}")
    except Exception as e:
        logger.error(f"Jira sync job error: {e}")


async def _standup_job():
    """9AM Mon–Fri: generate AI standups for all active users."""
    try:
        from app.core.database import SessionLocal
        from app.models.user import User
        from app.models.notification import Notification
        from app.models.base import gen_uuid
        from app.ai.documents import generate_standup

        db    = SessionLocal()
        today = date.today()

        # Only run on weekdays
        if today.weekday() >= 5:
            db.close()
            return

        users = db.query(User).filter(User.status == "active").all()
        for user in users:
            try:
                await generate_standup(user.id, user.org_id, today.isoformat(), db)
                # Notify the user that their standup is ready
                notif = Notification(
                    id=gen_uuid(),
                    org_id=user.org_id,
                    user_id=user.id,
                    type="standup_ready",
                    title="Your standup for today is ready",
                    body="NOVA has drafted your standup. Review and share it with your team.",
                    link="/standup",
                )
                db.add(notif)
                db.commit()
                logger.info(f"Standup generated for user {user.id}")
            except Exception as e:
                logger.warning(f"Standup job failed for user {user.id}: {e}")
                db.rollback()

        db.close()
    except Exception as e:
        logger.error(f"Standup job error: {e}")


async def _burnrate_job():
    """Hourly: check client budgets and fire alerts at 70/85/100/110%."""
    try:
        from app.core.database import SessionLocal
        from app.models.organisation import Organisation
        from app.models.client import ClientBudget, BurnRateAlert
        from app.models.notification import Notification
        from app.models.user import User
        from app.models.ticket import Worklog, JiraTicket
        from app.models.manual_entry import ManualEntry
        from app.models.base import gen_uuid
        from app.ai.nova import chat
        from sqlalchemy import func

        db    = SessionLocal()
        today = date.today()
        m, y  = today.month, today.year

        orgs = db.query(Organisation).all()

        for org in orgs:
            budgets = db.query(ClientBudget).filter(
                ClientBudget.org_id == org.id,
                ClientBudget.month  == m,
                ClientBudget.year   == y,
            ).all()

            for budget in budgets:
                # Total hours used
                wl = db.query(func.sum(Worklog.hours)).join(
                    JiraTicket, Worklog.ticket_id == JiraTicket.id
                ).filter(
                    JiraTicket.org_id    == org.id,
                    JiraTicket.client    == budget.client,
                    JiraTicket.is_deleted == False,
                    func.extract("month", Worklog.log_date) == m,
                    func.extract("year",  Worklog.log_date) == y,
                ).scalar() or 0

                me = db.query(func.sum(ManualEntry.hours)).filter(
                    ManualEntry.org_id == org.id,
                    ManualEntry.client == budget.client,
                    func.extract("month", ManualEntry.entry_date) == m,
                    func.extract("year",  ManualEntry.entry_date) == y,
                ).scalar() or 0

                hours_used = float(wl) + float(me)
                burn_pct   = hours_used / float(budget.budget_hours) * 100 if budget.budget_hours else 0

                # Check thresholds
                for threshold in [70, 85, 100, 110]:
                    if burn_pct >= threshold:
                        # Check if alert already sent for this threshold this month
                        already = db.query(BurnRateAlert).filter(
                            BurnRateAlert.org_id        == org.id,
                            BurnRateAlert.client        == budget.client,
                            BurnRateAlert.threshold_pct == threshold,
                            func.extract("month", BurnRateAlert.notified_at) == m,
                            func.extract("year",  BurnRateAlert.notified_at) == y,
                        ).first()

                        if already:
                            continue

                        # Generate NOVA summary
                        days_remaining = (
                            date(y, m % 12 + 1, 1) - today
                        ).days if m < 12 else (date(y + 1, 1, 1) - today).days

                        try:
                            nova_summary = await chat(
                                f"Client '{budget.client}' has used {hours_used:.1f} of "
                                f"{float(budget.budget_hours):.1f} budgeted hours ({burn_pct:.0f}%) "
                                f"with {days_remaining} days remaining in the month. "
                                "Write a concise 2-sentence alert for the project manager.",
                                temperature=0,
                                max_tokens=150,
                            )
                        except Exception:
                            nova_summary = (
                                f"Client {budget.client} is at {burn_pct:.0f}% budget utilisation "
                                f"({hours_used:.1f}/{float(budget.budget_hours):.1f} hrs)."
                            )

                        alert = BurnRateAlert(
                            id=gen_uuid(),
                            org_id=org.id,
                            client=budget.client,
                            threshold_pct=threshold,
                            hours_used=hours_used,
                            hours_budget=float(budget.budget_hours),
                            nova_summary=nova_summary,
                        )
                        db.add(alert)

                        # Notify PM and finance_viewer roles
                        managers = db.query(User).filter(
                            User.org_id == org.id,
                            User.status == "active",
                            User.role.in_(["admin", "engineering_manager", "finance_viewer"]),
                        ).all()

                        for mgr in managers:
                            notif = Notification(
                                id=gen_uuid(),
                                org_id=org.id,
                                user_id=mgr.id,
                                type="burn_rate_alert",
                                title=f"⚠️ {budget.client} at {threshold}% budget",
                                body=nova_summary,
                                link=f"/clients/burn-rate",
                            )
                            db.add(notif)

                        db.commit()
                        logger.info(f"Burn rate alert fired: {budget.client} at {threshold}%")

        db.close()
    except Exception as e:
        logger.error(f"Burn rate job error: {e}")


async def _gaps_job():
    """Weekly Monday 8AM: detect knowledge gaps for all orgs."""
    try:
        from app.core.database import SessionLocal
        from app.models.organisation import Organisation
        from app.ai.knowledge_gaps import detect_knowledge_gaps

        db   = SessionLocal()
        orgs = db.query(Organisation).all()

        for org in orgs:
            try:
                gaps = await detect_knowledge_gaps(org.id, db)
                logger.info(f"Knowledge gaps detected for org {org.id}: {len(gaps)} gaps")
            except Exception as e:
                logger.warning(f"Gap detection failed for org {org.id}: {e}")

        db.close()
    except Exception as e:
        logger.error(f"Gaps job error: {e}")


# ── Lifecycle ──────────────────────────────────────────────────────────────

def start_scheduler() -> None:
    """Register all cron/interval jobs and start the scheduler."""
    scheduler.add_job(
        _jira_sync_job,
        "interval",
        minutes=settings.sync_interval_minutes,
        id="jira_sync",
        replace_existing=True,
    )
    scheduler.add_job(
        _standup_job,
        "cron",
        hour=9, minute=0,
        day_of_week="mon-fri",
        id="standup_daily",
        replace_existing=True,
    )
    scheduler.add_job(
        _burnrate_job,
        "interval",
        hours=1,
        id="burnrate_hourly",
        replace_existing=True,
    )
    scheduler.add_job(
        _gaps_job,
        "cron",
        day_of_week="mon",
        hour=8, minute=0,
        id="gaps_weekly",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        f"Scheduler started — sync every {settings.sync_interval_minutes}m, "
        "standup 9AM daily, burnrate hourly, gaps weekly"
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
