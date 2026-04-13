"""
seeds/seed_all.py — Master seed runner.

Usage:
  cd trackly-backend
  python seeds/seed_all.py

Order:
  1. seed_tickets.py — 35 tickets + embeddings
  2. seed_wiki.py    — 4 spaces + 12 wiki pages + embeddings

Requirements:
  - Database must be running and migrated (alembic upgrade head)
  - At least one Organisation + one User must exist
  - NOVA/Ollama optional — embedding falls back gracefully if unavailable
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app.core.database import SessionLocal
from app.models.organisation import Organisation
from app.models.user import User


def main():
    db = SessionLocal()
    org  = db.query(Organisation).first()
    user = db.query(User).filter(User.org_id == org.id).first() if org else None
    db.close()

    if not org:
        print("❌ No organisation found.")
        print("   Create one first: POST /api/orgs  or run setup.")
        sys.exit(1)

    if not user:
        print("❌ No user found for this org.")
        print("   Create a user first via POST /api/employees/sync")
        sys.exit(1)

    print(f"🌱 Seeding Trackly for org: {org.name} ({org.id})")
    print(f"   Author user: {user.name} ({user.id})\n")

    # ── Step 1: Tickets ────────────────────────────────────────────────────────
    print("━━━ Step 1: Seed Tickets (35) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    from seeds.seed_tickets import seed_tickets
    seed_tickets(org.id, embed=True)

    print()

    # ── Step 2: Wiki ───────────────────────────────────────────────────────────
    print("━━━ Step 2: Seed Wiki (4 spaces + 12 pages) ━━━━━━━━━━━━━━")
    from seeds.seed_wiki import seed_wiki
    seed_wiki(org.id, user.id, embed=True)

    print()
    print("🎉 All done! Trackly is ready to demo.")
    print()
    print("Test commands:")
    print("  POST /api/tickets/ai-analyze  { \"text\": \"login page broken on mobile\" }")
    print("  POST /api/search              { \"query\": \"rate limiting\" }")
    print("  GET  /api/nova/status")


if __name__ == "__main__":
    main()
