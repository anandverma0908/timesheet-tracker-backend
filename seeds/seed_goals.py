"""Seed script for Goals / OKRs."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.goal import Goal
from app.models.user import User


def seed_goals():
    db = SessionLocal()
    try:
        # Find the first org to associate goals with
        user = db.query(User).first()
        if not user:
            print("No users found. Create a user first.")
            return

        org_id = user.org_id

        # Check if goals already exist
        existing = db.query(Goal).filter(Goal.org_id == org_id).first()
        if existing:
            print(f"Goals already seeded for org {org_id}")
            return

        goals = [
            {
                "quarter": "Q2 2025",
                "title": "Reduce API latency by 40%",
                "description": "Make Trackly feel instant. All API endpoints should respond under 200ms at p99.",
                "owner": "Priya S.",
                "status": "at_risk",
                "overall_progress": 52,
                "key_results": [
                    {"id": "kr1", "title": "p99 latency < 200ms on /api/tickets", "current": 280, "target": 200, "unit": "ms", "linked_tickets": ["TRK-134", "TRK-141"], "status": "at_risk"},
                    {"id": "kr2", "title": "Database query time < 50ms avg", "current": 48, "target": 50, "unit": "ms", "linked_tickets": ["TRK-129"], "status": "on_track"},
                    {"id": "kr3", "title": "Nova query response < 3s p95", "current": 2.1, "target": 3, "unit": "s", "linked_tickets": ["TRK-156"], "status": "on_track"},
                ],
                "linked_sprints": ["Sprint 8", "Sprint 9"],
            },
            {
                "quarter": "Q2 2025",
                "title": "Nova answers 80% of process questions accurately",
                "description": "Nova should be the team's first stop for 'how do we do X' questions, not Slack.",
                "owner": "Anand V.",
                "status": "behind",
                "overall_progress": 31,
                "key_results": [
                    {"id": "kr4", "title": "30+ ADRs in Decisions log", "current": 5, "target": 30, "unit": "records", "linked_tickets": ["TRK-161"], "status": "behind"},
                    {"id": "kr5", "title": "10+ runbooks in Processes", "current": 2, "target": 10, "unit": "runbooks", "linked_tickets": ["TRK-163"], "status": "behind"},
                    {"id": "kr6", "title": "Nova accuracy score ≥ 80% (internal eval)", "current": 61, "target": 80, "unit": "%", "linked_tickets": [], "status": "behind"},
                ],
                "linked_sprints": ["Sprint 9"],
            },
            {
                "quarter": "Q2 2025",
                "title": "Ship duplicate detection + smart routing to 100% of users",
                "description": "The two biggest AI features that make Trackly feel magical in demos. Must be in production.",
                "owner": "Rahul M.",
                "status": "on_track",
                "overall_progress": 78,
                "key_results": [
                    {"id": "kr7", "title": "Duplicate detection live banner in create drawer", "current": 1, "target": 1, "unit": "shipped", "linked_tickets": ["TRK-152"], "status": "on_track"},
                    {"id": "kr8", "title": "Smart routing UI with explanation", "current": 0, "target": 1, "unit": "shipped", "linked_tickets": ["TRK-156"], "status": "at_risk"},
                    {"id": "kr9", "title": "95% uptime for AI features", "current": 99.1, "target": 95, "unit": "%", "linked_tickets": [], "status": "complete"},
                ],
                "linked_sprints": ["Sprint 8", "Sprint 9"],
            },
        ]

        for g in goals:
            goal = Goal(org_id=org_id, **g)
            db.add(goal)

        db.commit()
        print(f"Seeded {len(goals)} goals for org {org_id}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_goals()
