"""
seeds/seed_demo.py — Full demo seed for Trackly.

Creates:
  - Sprint 2 activated (active) with 18 real tickets from varied pods
  - Sprint 3 created (planning)
  - Story points set on all sprint tickets
  - Status diversity for Kanban demo

Usage:
  cd trackly-backend
  source venv/bin/activate
  python seeds/seed_demo.py
"""

import sys, os, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from datetime import date, timedelta
from app.core.database import SessionLocal
from app.models.organisation import Organisation
from app.models.user import User
from app.models.ticket import JiraTicket
from app.models.sprint import Sprint

db = SessionLocal()

org   = db.query(Organisation).first()
users = db.query(User).filter(User.org_id == org.id).all()

print(f"Org: {org.name}")
print(f"Users: {len(users)}")

# ── 1. Activate Sprint 2 ─────────────────────────────────────────────────────
sprint2 = db.query(Sprint).filter(Sprint.name == "Sprint 2", Sprint.org_id == org.id).first()
if sprint2:
    sprint2.status     = "active"
    sprint2.goal       = "Stabilise DPAI forecasting engine, SNOP supply chain fixes, DS model performance"
    sprint2.start_date = date.today() - timedelta(days=3)
    sprint2.end_date   = date.today() + timedelta(days=11)
    db.commit()
    print(f"✅ Sprint 2 activated  [{sprint2.id}]  ends {sprint2.end_date}")
else:
    print("❌ Sprint 2 not found")
    sys.exit(1)

# ── 2. Create Sprint 3 (planning) ────────────────────────────────────────────
s3 = db.query(Sprint).filter(Sprint.name == "Sprint 3", Sprint.org_id == org.id).first()
if not s3:
    s3 = Sprint(
        org_id     = org.id,
        name       = "Sprint 3",
        goal       = "CARX analytics dashboard + DE infrastructure hardening",
        start_date = date.today() + timedelta(days=12),
        end_date   = date.today() + timedelta(days=26),
        status     = "planning",
    )
    db.add(s3)
    db.commit()
    print(f"✅ Sprint 3 created (planning) [{s3.id}]")
else:
    print(f"ℹ️  Sprint 3 already exists")

# ── 3. Detach any tickets already pointing at sprint2 (fresh start) ──────────
db.query(JiraTicket).filter(
    JiraTicket.sprint_id == sprint2.id,
    JiraTicket.org_id == org.id,
).update({"sprint_id": None, "story_points": None})
db.commit()
print("   Cleared old sprint2 ticket links")

# ── 4. Assign real tickets to Sprint 2 with varied statuses/SP ───────────────
TICKET_PLAN = [
    # pod,   target_status,  story_points
    ("DPAI", "In Progress",  5),
    ("DPAI", "In Progress",  3),
    ("DPAI", "In Review",    8),
    ("DPAI", "To Do",        5),
    ("DPAI", "Blocked",      3),
    ("DPAI", "Done",         5),
    ("DPAI", "Done",         3),
    ("DS",   "In Progress",  8),
    ("DS",   "To Do",        5),
    ("DS",   "Done",         3),
    ("SNOP", "In Review",    5),
    ("SNOP", "In Progress",  3),
    ("SNOP", "To Do",        2),
    ("CARX", "In Progress",  5),
    ("CARX", "Done",         8),
    ("DE",   "To Do",        3),
    ("DE",   "In Progress",  5),
    ("DE",   "Blocked",      2),
]

added = 0
used_ids = set()

for pod, status, sp in TICKET_PLAN:
    # Pick a random ticket from this pod that hasn't been used yet
    candidates = (
        db.query(JiraTicket)
        .filter(
            JiraTicket.org_id    == org.id,
            JiraTicket.pod       == pod,
            JiraTicket.sprint_id == None,
            JiraTicket.is_deleted == False,
        )
        .order_by(JiraTicket.synced_at.desc())
        .limit(100)
        .all()
    )
    # Pick one not already used
    ticket = next((t for t in candidates if t.id not in used_ids), None)
    if not ticket:
        # Fallback: any ticket from this pod
        ticket = (
            db.query(JiraTicket)
            .filter(JiraTicket.org_id == org.id, JiraTicket.pod == pod, JiraTicket.is_deleted == False)
            .filter(JiraTicket.id.notin_(list(used_ids)))
            .first()
        )
    if not ticket:
        print(f"  ⚠️  No ticket for pod={pod}")
        continue

    ticket.sprint_id    = sprint2.id
    ticket.story_points = sp
    ticket.status       = status
    used_ids.add(ticket.id)
    added += 1

db.commit()
print(f"✅ Assigned {added} tickets to Sprint 2")

# ── 5. Sprint 1 — make sure it has completed tickets ─────────────────────────
sprint1 = db.query(Sprint).filter(Sprint.name == "Sprint 1", Sprint.org_id == org.id).first()
if sprint1:
    s1_count = db.query(JiraTicket).filter(JiraTicket.sprint_id == sprint1.id).count()
    if s1_count < 5:
        # Add 8 completed DPAI tickets
        done_tickets = (
            db.query(JiraTicket)
            .filter(
                JiraTicket.org_id    == org.id,
                JiraTicket.pod       == "DPAI",
                JiraTicket.status    == "Done",
                JiraTicket.sprint_id == None,
                JiraTicket.is_deleted == False,
            )
            .limit(8)
            .all()
        )
        for t in done_tickets:
            t.sprint_id    = sprint1.id
            t.story_points = random.choice([3, 5, 8])
        db.commit()
        print(f"✅ Added {len(done_tickets)} completed tickets to Sprint 1")
    else:
        print(f"ℹ️  Sprint 1 already has {s1_count} tickets")

# ── 6. Summary ────────────────────────────────────────────────────────────────
for sp_name in ["Sprint 1", "Sprint 2", "Sprint 3"]:
    sp = db.query(Sprint).filter(Sprint.name == sp_name, Sprint.org_id == org.id).first()
    if sp:
        tc = db.query(JiraTicket).filter(JiraTicket.sprint_id == sp.id).count()
        total_sp = db.query(JiraTicket).filter(JiraTicket.sprint_id == sp.id).all()
        pts = sum(t.story_points or 0 for t in total_sp)
        done_pts = sum(t.story_points or 0 for t in total_sp if t.status in ("Done","Closed","Resolved"))
        print(f"   {sp_name:10} [{sp.status:10}] tickets={tc:3}  SP={pts:3}  done_SP={done_pts:3}")

db.close()

print()
print("🎉 Demo seed complete!")
print()
print("Login: 3scadmin@3scsolution.com / password123")
print()
print("Feature test routes:")
print("  /tickets      — 26k+ tickets, create with AI analysis")
print("  /kanban       — Drag cards between columns")
print("  /sprints      — Sprint 2 active with 18 tickets across 5 pods")
print("  /wiki         — 4 spaces, 13 pages, rich editor")
print("  Cmd+K         — Semantic search + NOVA mode")
print("  Nova widget   — Floating ✨ button bottom-right")
