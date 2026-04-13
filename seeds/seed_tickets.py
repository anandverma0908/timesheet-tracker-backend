"""
seeds/seed_tickets.py — Insert 35 seed tickets (DPAI + SNOP) + generate embeddings.
Run via: python seeds/seed_all.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app.core.database import SessionLocal
from app.models.ticket import JiraTicket
from app.models.base import gen_uuid
from datetime import date

TICKETS = [
    # ── DPAI (20 tickets) ──────────────────────────────────────────────────────
    {"jira_key":"DPAI-1018","summary":"Forecasting UI — drag & drop column reorder","issue_type":"Story","status":"In Progress","assignee":"Anand Verma","pod":"DPAI","priority":"High","story_points":8},
    {"jira_key":"DPAI-1015","summary":"JFL UAT environment slow to load (DFU drawer)","issue_type":"Bug","status":"In Progress","assignee":"Mohit Kapoor","pod":"DPAI","priority":"High","story_points":5},
    {"jira_key":"DPAI-1012","summary":"Group by pagination fails on 2nd page","issue_type":"Bug","status":"In Review","assignee":"Prakash Kumar","pod":"DPAI","priority":"Medium","story_points":3},
    {"jira_key":"DPAI-1010","summary":"Analytics dashboard redesign","issue_type":"Epic","status":"In Review","assignee":"Anand Verma","pod":"DPAI","priority":"High","story_points":13},
    {"jira_key":"DPAI-1009","summary":"Login page redesign with password strength","issue_type":"Task","status":"Done","assignee":"Anand Verma","pod":"DPAI","priority":"Low","story_points":5},
    {"jira_key":"DPAI-7018","summary":"Data grid not visible until scroll on QA env","issue_type":"Bug","status":"Done","assignee":"Anand Verma","pod":"DPAI","priority":"High","story_points":3},
    {"jira_key":"DPAI-7013","summary":"Drag & drop and hide column not working","issue_type":"Bug","status":"Done","assignee":"Prakash Kumar","pod":"DPAI","priority":"High","story_points":3},
    {"jira_key":"DPAI-7011","summary":"Unnecessary API call on group by 2nd page","issue_type":"Bug","status":"Done","assignee":"Anand Verma","pod":"DPAI","priority":"Medium","story_points":2},
    {"jira_key":"DPAI-7000","summary":"Data grid display incorrect — QA Forecasting","issue_type":"Bug","status":"Done","assignee":"Anand Verma","pod":"DPAI","priority":"High","story_points":3},
    {"jira_key":"DPAI-6972","summary":"Rearrangement broken in manage column","issue_type":"Bug","status":"Done","assignee":"Prakash Kumar","pod":"DPAI","priority":"Medium","story_points":2},
    {"jira_key":"DPAI-6971","summary":"Manage column dropdowns editable in QA","issue_type":"Bug","status":"Done","assignee":"Anand Verma","pod":"DPAI","priority":"Low","story_points":1},
    {"jira_key":"DPAI-6856","summary":"JFL UAT — DFU info side drawer lag","issue_type":"Bug","status":"Done","assignee":"Anand Verma","pod":"DPAI","priority":"High","story_points":3},
    {"jira_key":"DPAI-1021","summary":"Refactor auth middleware for better performance","issue_type":"Story","status":"Backlog","assignee":"Anand Verma","pod":"DPAI","priority":"Medium","story_points":5},
    {"jira_key":"DPAI-1022","summary":"Add rate limiting to public APIs","issue_type":"Task","status":"Backlog","assignee":"Prakash Kumar","pod":"DPAI","priority":"Medium","story_points":3},
    {"jira_key":"DPAI-1019","summary":"Mobile responsive fixes for data grid","issue_type":"Bug","status":"Backlog","assignee":"Achal Kokatanoor","pod":"DPAI","priority":"Low","story_points":3},
    {"jira_key":"DPAI-1020","summary":"Dark mode support for forecasting screens","issue_type":"Story","status":"Backlog","assignee":"Mohit Kapoor","pod":"DPAI","priority":"Low","story_points":5},
    {"jira_key":"DPAI-1023","summary":"Export forecasting data to Excel","issue_type":"Task","status":"Backlog","assignee":"Swapnil Akash","pod":"DPAI","priority":"Low","story_points":2},
    {"jira_key":"DPAI-1024","summary":"Performance profiling — identify slow queries","issue_type":"Task","status":"Backlog","assignee":"Prakash Kumar","pod":"DPAI","priority":"Medium","story_points":3},
    {"jira_key":"DPAI-1025","summary":"Add Jest unit tests for grid component","issue_type":"Task","status":"Backlog","assignee":"Anand Verma","pod":"DPAI","priority":"Low","story_points":3},
    {"jira_key":"DPAI-1026","summary":"API documentation — Swagger cleanup","issue_type":"Task","status":"Backlog","assignee":"Mohit Kapoor","pod":"DPAI","priority":"Low","story_points":1},
    # ── SNOP (15 tickets) ──────────────────────────────────────────────────────
    {"jira_key":"SNOP-138","summary":"Edit button overlapping in Turkish language","issue_type":"Bug","status":"In Review","assignee":"Anand Verma","pod":"SNOP","priority":"Low","story_points":2},
    {"jira_key":"SNOP-139","summary":"SLA dashboard — overdue alerts not firing","issue_type":"Bug","status":"In Progress","assignee":"Aman Kumar Singh","pod":"SNOP","priority":"High","story_points":3},
    {"jira_key":"SNOP-140","summary":"Sprint capacity planning view","issue_type":"Story","status":"In Progress","assignee":"Akash Kumar","pod":"SNOP","priority":"Medium","story_points":5},
    {"jira_key":"SNOP-141","summary":"Vendor scorecard integration","issue_type":"Epic","status":"Backlog","assignee":"Ishu Rani","pod":"SNOP","priority":"Medium","story_points":13},
    {"jira_key":"SNOP-108","summary":"Filter panel overlapping grid on demand sensing","issue_type":"Bug","status":"Done","assignee":"Anand Verma","pod":"SNOP","priority":"High","story_points":2},
    {"jira_key":"SNOP-109","summary":"Blank page on pagination rows > 11","issue_type":"Bug","status":"Done","assignee":"Anand Verma","pod":"SNOP","priority":"High","story_points":2},
    {"jira_key":"SNOP-113","summary":"Something Went Wrong error in demand sensing window","issue_type":"Bug","status":"Done","assignee":"Anand Verma","pod":"SNOP","priority":"High","story_points":3},
    {"jira_key":"SNOP-142","summary":"Turkish locale — number formatting edge cases","issue_type":"Bug","status":"Backlog","assignee":"Akanksha","pod":"SNOP","priority":"Low","story_points":2},
    {"jira_key":"SNOP-143","summary":"Export supply plan to PDF","issue_type":"Task","status":"Backlog","assignee":"Ashish Kumar Gopalika","pod":"SNOP","priority":"Low","story_points":2},
    {"jira_key":"SNOP-144","summary":"Integrate with ERP system via REST","issue_type":"Epic","status":"Backlog","assignee":"Anoop Kumar Rai","pod":"SNOP","priority":"Medium","story_points":13},
    {"jira_key":"SNOP-145","summary":"Bulk import supplier data from CSV","issue_type":"Story","status":"Backlog","assignee":"Aastha Rai","pod":"SNOP","priority":"Medium","story_points":5},
    {"jira_key":"SNOP-146","summary":"Real-time stock level dashboard","issue_type":"Story","status":"Backlog","assignee":"Akash Kumar","pod":"SNOP","priority":"Medium","story_points":5},
    {"jira_key":"SNOP-147","summary":"AI demand forecasting model — backtest","issue_type":"Epic","status":"Backlog","assignee":"Prakash Kumar","pod":"SNOP","priority":"High","story_points":13},
    {"jira_key":"SNOP-148","summary":"Notification system — low stock alerts","issue_type":"Story","status":"Backlog","assignee":"Mohit Kapoor","pod":"SNOP","priority":"Medium","story_points":3},
    {"jira_key":"SNOP-149","summary":"Role-based supply chain view per region","issue_type":"Story","status":"Backlog","assignee":"Aman Kumar Singh","pod":"SNOP","priority":"Medium","story_points":5},
]


def seed_tickets(org_id: str, embed: bool = True):
    db = SessionLocal()
    inserted = 0

    try:
        for t in TICKETS:
            exists = db.query(JiraTicket).filter(
                JiraTicket.org_id == org_id,
                JiraTicket.jira_key == t["jira_key"],
            ).first()
            if exists:
                print(f"  skip {t['jira_key']} (already exists)")
                continue

            ticket = JiraTicket(
                id=gen_uuid(),
                org_id=org_id,
                jira_key=t["jira_key"],
                project_key=t["jira_key"].split("-")[0],
                summary=t["summary"],
                issue_type=t["issue_type"],
                status=t["status"],
                assignee=t["assignee"],
                pod=t["pod"],
                priority=t["priority"],
                story_points=t.get("story_points"),
                hours_spent=0,
                is_deleted=False,
            )
            db.add(ticket)
            db.commit()
            db.refresh(ticket)
            inserted += 1
            print(f"  ✅ {t['jira_key']} — {t['summary'][:60]}")

            if embed:
                try:
                    import asyncio
                    from app.ai.search import embed_and_store_ticket
                    asyncio.run(embed_and_store_ticket(ticket.id, ticket.summary, "", db))
                    print(f"     🧠 embedded")
                except Exception as e:
                    print(f"     ⚠️  embed failed: {e}")

    finally:
        db.close()

    print(f"\n✅ Seeded {inserted} tickets")
    return inserted


if __name__ == "__main__":
    from app.core.database import SessionLocal
    db = SessionLocal()
    from app.models.organisation import Organisation
    org = db.query(Organisation).first()
    db.close()
    if not org:
        print("❌ No organisation found. Create one first via POST /api/orgs")
        sys.exit(1)
    print(f"Seeding tickets for org: {org.name} ({org.id})")
    seed_tickets(org.id)
