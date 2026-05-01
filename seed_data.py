"""
seed_data.py — Populate all Trackly tables with realistic demo data.
Run: cd trackly-backend && python3 seed_data.py
"""

import uuid, json, random
from datetime import datetime, date, timedelta
import psycopg2

DB = "postgresql://anandverma@localhost:5432/timesheet-tracker-db"
conn = psycopg2.connect(DB)
cur  = conn.cursor()

def uid(): return str(uuid.uuid4())
def now(): return datetime.utcnow()
def days_ago(n): return (date.today() - timedelta(days=n)).isoformat()
def days_from_now(n): return (date.today() + timedelta(days=n)).isoformat()

# ─── Known IDs ────────────────────────────────────────────────────────────────
ORG = "91da7ceb-c12d-4189-97aa-c4d2831b2e28"

USERS = {
    "Admin":            "2aa88777-67d3-46b5-917d-4f7d0454a61a",
    "Anoop Rai":        "ffeee356-7818-4208-92c2-1cdb106ef8dd",
    "Abhishek Jain":    "043d7e8b-bbdf-4dd5-a2d4-dc53c72c2d26",
    "Seva Srinivasan":  "38023d56-536f-4a53-80c9-c234e860afa0",
    "Aman Singh":       "6de0ac1b-cfe8-47b5-ac0e-f33eae6500a1",
    "Ashish Gopallika": "3e05f19f-2516-49a9-b611-abd82cee869a",
    "Nihar Bansal":     "9126bde3-badc-4e62-b005-d384be862391",
    "Aastha Rai":       "d3a22bfc-a427-4d69-bab5-db74621edec0",
    "Akanksha Sharma":  "8630309f-6ac9-43d6-bc31-bb5c80debd3a",
    "Ishu Rana":        "252192a8-564e-48d4-93ca-03d94e6a2401",
    "Anand Verma":      "5de520a5-1066-40ba-a811-570f4cc13b18",
    "Akash Kumar":      "9529ac0b-765d-43c2-95ae-4a5292b95888",
}
EMAILS = {
    n: f"{n.lower().replace(' ', '.')}.@3scsolution.com" for n in USERS
}
EMAILS = {
    "Admin":            "admin@3scsolution.com",
    "Anoop Rai":        "anoop.rai@3scsolution.com",
    "Abhishek Jain":    "abhishek.jain@3scsolution.com",
    "Seva Srinivasan":  "seva.srinivasan@3scsolution.com",
    "Aman Singh":       "aman.singh@3scsolution.com",
    "Ashish Gopallika": "ashish.gopallika@3scsolution.com",
    "Nihar Bansal":     "nihar.bansal@3scsolution.com",
    "Aastha Rai":       "aastha.rai@3scsolution.com",
    "Akanksha Sharma":  "akanksha.sharma@3scsolution.com",
    "Ishu Rana":        "ishu.rana@3scsolution.com",
    "Anand Verma":      "anand.verma@3scsolution.com",
    "Akash Kumar":      "akash.kumar@3scsolution.com",
}

ENGINEERS = ["Aman Singh", "Ashish Gopallika", "Nihar Bansal", "Aastha Rai",
             "Akanksha Sharma", "Ishu Rana", "Anand Verma", "Akash Kumar"]
LEADS     = ["Seva Srinivasan", "Abhishek Jain", "Anoop Rai"]
ALL_DEV   = ENGINEERS + LEADS

PODS = ["DPAI", "NOVA", "AURA", "PULSE"]
CLIENTS = ["Accenture", "TechCorp", "FinanceGroup", "RetailCo", "HealthFirst"]

POD_CLIENT = {
    "DPAI":  "Accenture",
    "NOVA":  "TechCorp",
    "AURA":  "FinanceGroup",
    "PULSE": "RetailCo",
}
POD_LEAD = {
    "DPAI":  "Abhishek Jain",
    "NOVA":  "Anoop Rai",
    "AURA":  "Seva Srinivasan",
    "PULSE": "Abhishek Jain",
}
POD_ENGINEERS = {
    "DPAI":  ["Aastha Rai", "Akanksha Sharma", "Anand Verma"],
    "NOVA":  ["Aman Singh", "Nihar Bansal", "Akash Kumar"],
    "AURA":  ["Ashish Gopallika", "Ishu Rana"],
    "PULSE": ["Aman Singh", "Aastha Rai", "Nihar Bansal"],
}

STATUSES   = ["Backlog", "To Do", "In Progress", "In Review", "Done", "Blocked"]
PRIORITIES = ["Highest", "High", "Medium", "Low"]
ITYPES     = ["Story", "Bug", "Task", "Improvement", "Subtask"]
FIB        = [1, 2, 3, 5, 8, 13]

EXISTING_SPRINT_ID = "0cfdbbc9-5d00-4dde-a227-6b012c85ad98"

print("=== Seeding Trackly DB ===")

# ─── 1. UPDATE existing users with pod assignments ─────────────────────────
print("1. Updating user pod assignments...")
user_pod = {}
for pod, engineers in POD_ENGINEERS.items():
    for eng in engineers:
        user_pod[eng] = pod
for lead, pod in [("Abhishek Jain","DPAI"), ("Anoop Rai","NOVA"), ("Seva Srinivasan","AURA")]:
    user_pod[lead] = pod

for name, pod in user_pod.items():
    cur.execute("UPDATE users SET pod=%s WHERE id=%s", (pod, USERS[name]))
conn.commit()
print(f"   Updated {len(user_pod)} users")

# ─── 2. SPRINTS ────────────────────────────────────────────────────────────
print("2. Creating sprints...")
sprint_ids = {"DPAI": EXISTING_SPRINT_ID}  # reuse existing active sprint

# Update existing sprint with proper dates
cur.execute("""
    UPDATE sprints SET start_date=%s, end_date=%s, goal=%s, velocity=42
    WHERE id=%s
""", (days_ago(7), days_from_now(7), "Complete AI dashboard MVP and fix critical bugs", EXISTING_SPRINT_ID))

for pod in ["NOVA", "AURA", "PULSE"]:
    sid = uid()
    sprint_ids[pod] = sid
    cur.execute("""
        INSERT INTO sprints (id, org_id, pod, name, goal, start_date, end_date, status, velocity)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s)
    """, (sid, ORG, pod, f"{pod} — Sprint 3",
          f"Deliver {pod} core features and stabilize platform",
          days_ago(5), days_from_now(9), random.randint(30, 55)))

# Completed sprints for each pod
for pod in PODS:
    for i in [1, 2]:
        offset = i * 14
        cur.execute("""
            INSERT INTO sprints (id, org_id, pod, name, goal, start_date, end_date, status, velocity)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'completed',%s)
        """, (uid(), ORG, pod,
              f"{pod} — Sprint {3 - i}",
              f"Sprint {3-i} goals for {pod}",
              days_ago(14 * i + 14), days_ago(14 * i),
              random.randint(28, 50)))

conn.commit()
print(f"   Created sprints for all pods")

# ─── 3. EPICS ─────────────────────────────────────────────────────────────
print("3. Creating epics...")
epic_ids = {}  # pod -> [epic_id, ...]
cur.execute("SELECT id, pod FROM epics WHERE org_id=%s", (ORG,))
for row in cur.fetchall():
    pod = row[1]
    epic_ids.setdefault(pod, []).append(row[0])

EPIC_DEFS = {
    "DPAI": [
        ("AI Dashboard v2", "#6366f1"),
        ("Data Pipeline Refactor", "#f59e0b"),
        ("Auth & Permissions", "#10b981"),
    ],
    "NOVA": [
        ("Search & Discovery", "#3b82f6"),
        ("Notification Engine", "#ef4444"),
        ("API Gateway v3", "#8b5cf6"),
    ],
    "AURA": [
        ("Payment Processing", "#06b6d4"),
        ("Reporting Module", "#f97316"),
        ("Mobile Optimization", "#84cc16"),
    ],
    "PULSE": [
        ("Analytics Platform", "#ec4899"),
        ("Realtime Events", "#14b8a6"),
        ("Client Portal", "#a855f7"),
    ],
}

for pod, defs in EPIC_DEFS.items():
    for title, color in defs:
        if pod in epic_ids and len(epic_ids[pod]) >= len(defs):
            break  # skip if enough epics exist
        eid = uid()
        epic_ids.setdefault(pod, []).append(eid)
        cur.execute("""
            INSERT INTO epics (id, org_id, pod, title, color, start_date, end_date, progress, task_count, completed_count)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (eid, ORG, pod, title, color,
              days_ago(30), days_from_now(30),
              random.randint(10, 80),
              random.randint(5, 20),
              random.randint(2, 8)))

conn.commit()
print(f"   Epics created for all pods")

# ─── 4. TICKETS ────────────────────────────────────────────────────────────
print("4. Creating tickets...")

TICKET_TEMPLATES = {
    "DPAI": [
        ("Implement real-time data refresh on dashboard", "Story", "High", "In Progress", 8),
        ("Add export to Excel functionality", "Story", "Medium", "To Do", 5),
        ("Fix null pointer in widget renderer", "Bug", "Highest", "In Progress", 3),
        ("Dashboard loads slow for large datasets", "Bug", "High", "In Review", 2),
        ("Add pagination to ticket list", "Improvement", "Medium", "Done", 3),
        ("Refactor chart components for reusability", "Task", "Medium", "Done", 5),
        ("Dark mode support for dashboard", "Story", "Low", "Backlog", 8),
        ("Write unit tests for data transformer", "Task", "Medium", "In Progress", 3),
        ("Fix date filter not respecting timezone", "Bug", "High", "Done", 2),
        ("Implement drag-and-drop for widget layout", "Story", "High", "Backlog", 13),
        ("Optimize SQL queries in analytics module", "Improvement", "High", "In Review", 5),
        ("Add keyboard shortcuts to ticket detail view", "Improvement", "Low", "Backlog", 2),
        ("Deprecate legacy v1 API endpoints", "Task", "Medium", "To Do", 3),
        ("User preference persistence for filters", "Story", "Medium", "In Progress", 5),
        ("Fix XSS vulnerability in comment renderer", "Bug", "Highest", "Done", 1),
        ("Create API documentation for dashboard endpoints", "Task", "Low", "Backlog", 3),
        ("Implement rate limiting on public endpoints", "Story", "High", "To Do", 5),
        ("Multi-language support (i18n) scaffold", "Story", "Low", "Backlog", 13),
        ("Fix broken avatar upload on profile page", "Bug", "Medium", "Done", 1),
        ("Sprint velocity chart shows wrong data", "Bug", "High", "Blocked", 2),
    ],
    "NOVA": [
        ("Implement semantic search with embeddings", "Story", "High", "In Progress", 13),
        ("Add voice search capability", "Story", "Medium", "Backlog", 8),
        ("Fix search results ranking algorithm", "Bug", "High", "In Review", 5),
        ("Notification batching to reduce spam", "Improvement", "High", "In Progress", 5),
        ("Real-time notification via WebSocket", "Story", "High", "To Do", 8),
        ("API Gateway rate limiting per tenant", "Story", "Highest", "In Progress", 8),
        ("Add search filters for date range", "Story", "Medium", "Done", 5),
        ("Fix duplicate notifications on reconnect", "Bug", "Medium", "Done", 2),
        ("Migrate notification queue to Redis", "Task", "High", "In Progress", 5),
        ("Search index auto-rebuild on data change", "Story", "Medium", "Backlog", 8),
        ("Write load tests for search API", "Task", "Medium", "To Do", 3),
        ("Fix 503 error on search under load", "Bug", "Highest", "In Review", 3),
        ("Add notification preference per channel", "Story", "Medium", "Blocked", 5),
        ("Gateway circuit breaker implementation", "Story", "High", "To Do", 8),
        ("Deprecate XML response format in API", "Task", "Low", "Done", 2),
        ("Search analytics dashboard", "Story", "Medium", "Backlog", 8),
        ("Fix auth token refresh race condition", "Bug", "High", "In Progress", 3),
        ("Add webhook retry with exponential backoff", "Improvement", "Medium", "Done", 3),
        ("Search spell correction using edit distance", "Story", "Low", "Backlog", 8),
        ("API versioning strategy documentation", "Task", "Low", "Done", 2),
    ],
    "AURA": [
        ("PCI-DSS compliance audit for payment module", "Story", "Highest", "In Progress", 13),
        ("Add 3D Secure authentication flow", "Story", "High", "To Do", 8),
        ("Fix decimal rounding error in invoice totals", "Bug", "Highest", "In Review", 2),
        ("Scheduled report generation (PDF)", "Story", "High", "In Progress", 8),
        ("Add drill-down to monthly expense report", "Improvement", "Medium", "Done", 5),
        ("Mobile checkout flow optimization", "Story", "High", "Backlog", 13),
        ("Fix payment gateway timeout handling", "Bug", "High", "Done", 3),
        ("Refund processing workflow", "Story", "Medium", "In Progress", 8),
        ("Report template builder UI", "Story", "Medium", "To Do", 8),
        ("Fix CSV export missing last row", "Bug", "Medium", "Done", 1),
        ("Add Apple Pay / Google Pay support", "Story", "High", "Backlog", 13),
        ("Payment reconciliation batch job", "Task", "High", "In Review", 5),
        ("Optimize report query with materialized views", "Improvement", "High", "In Progress", 5),
        ("Mobile app performance profiling", "Task", "Medium", "Done", 3),
        ("Fix offline mode data sync conflict", "Bug", "High", "Blocked", 5),
        ("Add multi-currency support", "Story", "Medium", "Backlog", 13),
        ("Fraud detection rule engine", "Story", "Highest", "To Do", 13),
        ("Write E2E tests for checkout flow", "Task", "High", "In Progress", 5),
        ("Fix dark mode contrast on mobile", "Bug", "Low", "Done", 1),
        ("Payment notification email template", "Task", "Low", "Done", 2),
    ],
    "PULSE": [
        ("Build real-time event streaming pipeline", "Story", "High", "In Progress", 13),
        ("Client portal SSO integration", "Story", "High", "To Do", 8),
        ("Analytics metrics aggregation job", "Story", "High", "In Progress", 8),
        ("Fix event deduplication logic", "Bug", "High", "In Review", 3),
        ("Add client-specific dashboard views", "Story", "Medium", "Backlog", 8),
        ("Kafka consumer lag monitoring", "Improvement", "High", "Done", 5),
        ("Client onboarding wizard", "Story", "Medium", "In Progress", 8),
        ("Fix memory leak in event processor", "Bug", "Highest", "Done", 5),
        ("Analytics export to BigQuery", "Story", "High", "To Do", 8),
        ("Client portal access control matrix", "Story", "High", "Blocked", 5),
        ("Event schema versioning", "Task", "Medium", "In Progress", 3),
        ("Fix chart rendering on Safari", "Bug", "Medium", "Done", 2),
        ("Add A/B test tracking in analytics", "Story", "Medium", "Backlog", 5),
        ("Kafka topic partitioning strategy", "Task", "High", "Done", 3),
        ("Write integration tests for event pipeline", "Task", "Medium", "In Progress", 3),
        ("Client usage quota enforcement", "Story", "High", "To Do", 8),
        ("Fix time series gap filling algorithm", "Bug", "Medium", "In Review", 3),
        ("Analytics alerting on threshold breach", "Story", "Medium", "Backlog", 5),
        ("Portal UI dark mode", "Improvement", "Low", "Backlog", 3),
        ("Performance benchmark dashboard", "Story", "Medium", "Done", 5),
    ],
}

ticket_ids = {}  # jira_key -> id
for pod, templates in TICKET_TEMPLATES.items():
    engineers = POD_ENGINEERS[pod]
    client    = POD_CLIENT[pod]
    sprint_id = sprint_ids[pod]
    epics     = epic_ids.get(pod, [None])

    for i, (summary, itype, priority, status, pts) in enumerate(templates, start=3 if pod == "DPAI" else 1):
        key = f"{pod}-{i}"
        tid = uid()
        ticket_ids[key] = tid
        assignee = random.choice(engineers + [POD_LEAD[pod]])
        hours = round(random.uniform(1, pts * 1.5), 1)
        est   = round(pts * 1.0, 1)
        is_in_sprint = (status in ["In Progress", "In Review", "Blocked"] or random.random() < 0.5)
        epic_id = random.choice(epics) if epics and random.random() < 0.6 else None

        cur.execute("""
            INSERT INTO jira_tickets
              (id, org_id, jira_key, project_key, project_name, summary, description,
               issue_type, priority, status, pod, client, assignee, assignee_email,
               reporter, story_points, hours_spent, original_estimate_hours,
               remaining_estimate_hours, sprint_id, epic_id, labels, is_deleted,
               jira_created, jira_updated, url)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s,%s)
        """, (
            tid, ORG, key, pod, f"{pod} Project", summary,
            f"## Context\n{summary}\n\n## Acceptance Criteria\n- Feature works as expected\n- Tests pass\n- Code reviewed",
            itype, priority, status, pod, client,
            assignee, EMAILS.get(assignee, ""),
            POD_LEAD[pod],
            pts, hours, est, max(0, est - hours),
            sprint_id if is_in_sprint else None,
            epic_id,
            json.dumps(["backend"] if i % 2 == 0 else ["frontend"]),
            days_ago(random.randint(1, 30)),
            days_ago(random.randint(0, 5)),
            f"https://jira.example.com/browse/{key}",
        ))

conn.commit()
print(f"   Created {sum(len(t) for t in TICKET_TEMPLATES.values())} tickets across {len(PODS)} pods")

# ─── 5. WORKLOGS ────────────────────────────────────────────────────────────
print("5. Creating worklogs...")
all_keys = list(ticket_ids.keys())
for key in random.sample(all_keys, min(40, len(all_keys))):
    tid = ticket_ids[key]
    pod = key.split("-")[0]
    engineers = POD_ENGINEERS.get(pod, ENGINEERS)
    for _ in range(random.randint(1, 3)):
        worker = random.choice(engineers)
        cur.execute("""
            INSERT INTO worklogs (id, ticket_id, author, author_email, log_date, hours, comment)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (uid(), tid, worker, EMAILS.get(worker, ""),
              days_ago(random.randint(0, 14)),
              round(random.uniform(0.5, 4.0), 1),
              random.choice(["Implementation work", "Bug investigation", "Code review", "Testing", "Documentation"])))

conn.commit()
print("   Worklogs created")

# ─── 6. TICKET COMMENTS ────────────────────────────────────────────────────
print("6. Adding ticket comments...")
COMMENTS = [
    "Looks good from my end, waiting for QA sign-off.",
    "Found a related issue in the staging environment. Investigating.",
    "PR is up: https://github.com/3sc/trackly/pull/142",
    "Blocked on dependency from the NOVA team. Following up.",
    "Testing done on my local. All cases pass.",
    "Need clarification on the acceptance criteria for step 3.",
    "This is now merged to main. Closing after deploy confirmation.",
    "Deployed to staging. Please verify.",
]
for key in random.sample(all_keys, min(30, len(all_keys))):
    tid = ticket_ids[key]
    pod = key.split("-")[0]
    engineers = POD_ENGINEERS.get(pod, ENGINEERS)
    for _ in range(random.randint(1, 3)):
        author = random.choice(engineers)
        cur.execute("""
            INSERT INTO ticket_comments (id, ticket_id, author_id, body, is_deleted, created_at, updated_at)
            VALUES (%s,%s,%s,%s,false,%s,%s)
        """, (uid(), tid, USERS[author],
              random.choice(COMMENTS),
              now() - timedelta(days=random.randint(0, 10)),
              now() - timedelta(days=random.randint(0, 5))))

conn.commit()
print("   Comments added")

# ─── 7. RELEASES ───────────────────────────────────────────────────────────
print("7. Creating releases...")
release_ids = {}
RELEASE_DEFS = {
    "DPAI":  [("v1.2.0", "Dashboard overhaul + bug fixes", "released", days_ago(14)),
              ("v1.3.0", "Performance improvements and new widgets", "in_progress", days_from_now(10)),
              ("v1.4.0", "Dark mode and i18n support", "planned", days_from_now(30))],
    "NOVA":  [("v2.1.0", "Semantic search launch", "released", days_ago(7)),
              ("v2.2.0", "Real-time notifications", "in_progress", days_from_now(14)),
              ("v2.3.0", "Search analytics", "planned", days_from_now(35))],
    "AURA":  [("v3.0.0", "PCI-DSS compliance + 3DS", "in_progress", days_from_now(21)),
              ("v3.1.0", "Multi-currency support", "planned", days_from_now(45))],
    "PULSE": [("v1.0.0", "Event streaming MVP", "released", days_ago(21)),
              ("v1.1.0", "Client portal beta", "in_progress", days_from_now(7)),
              ("v1.2.0", "Analytics export", "planned", days_from_now(28))],
}
for pod, rels in RELEASE_DEFS.items():
    release_ids[pod] = []
    for name, desc, status, rel_date in rels:
        rid = uid()
        release_ids[pod].append(rid)
        cur.execute("""
            INSERT INTO releases (id, org_id, pod, name, description, status, release_date)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (rid, ORG, pod, name, desc, status, rel_date))

conn.commit()
print("   Releases created")

# ─── 8. WIKI SPACES & PAGES ─────────────────────────────────────────────────
print("8. Creating wiki spaces and pages...")
cur.execute("SELECT id FROM wiki_spaces WHERE org_id=%s", (ORG,))
existing_ws = [r[0] for r in cur.fetchall()]

WIKI_SPACES = [
    ("Engineering Hub", "eng-hub", "Technical docs, runbooks, and architecture guides"),
    ("Product & Design", "product", "Product specs, wireframes, and design decisions"),
    ("Team Onboarding", "onboarding", "Onboarding guides and company handbook"),
    ("Client Docs", "clients", "Client-specific documentation and SLAs"),
]
ws_ids = {}
for name, slug, desc in WIKI_SPACES:
    wid = uid() if not existing_ws else existing_ws.pop(0) if existing_ws else uid()
    # Just insert fresh spaces (use ON CONFLICT DO NOTHING logic via unique slug)
    wid = uid()
    cur.execute("""
        INSERT INTO wiki_spaces (id, org_id, name, slug, description, access_level, created_at)
        VALUES (%s,%s,%s,%s,%s,'internal',%s)
        ON CONFLICT (org_id, slug) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description
        RETURNING id
    """, (wid, ORG, name, slug, desc, now()))
    row = cur.fetchone()
    ws_ids[slug] = row[0]

WIKI_PAGES = [
    # Engineering Hub
    ("eng-hub", None, "System Architecture Overview",
     "# System Architecture\n\nTrackly is a monorepo with a **FastAPI backend** and **React frontend**.\n\n## Services\n- API Gateway (FastAPI)\n- PostgreSQL 15\n- Redis (cache + queues)\n- pgvector (semantic search)\n\n## Deployment\nAll services run in Docker containers on AWS ECS.\n\n## Key Design Decisions\n- REST API (not GraphQL) for simplicity\n- JWT auth with refresh tokens\n- RBAC at the API layer"),
    ("eng-hub", None, "Local Development Setup",
     "# Local Dev Setup\n\n## Prerequisites\n- Python 3.11+\n- Node 18+\n- PostgreSQL 15\n- Docker (optional)\n\n## Steps\n1. Clone the repo\n2. `cp .env.example .env` and fill in values\n3. `pip install -r requirements.txt`\n4. `alembic upgrade head`\n5. `uvicorn app.main:app --reload`\n6. In another terminal: `cd frontend && npm install && npm run dev`"),
    ("eng-hub", None, "API Design Guidelines",
     "# API Design Guidelines\n\n## REST Conventions\n- Use plural nouns: `/tickets`, `/sprints`\n- Use HTTP verbs correctly (GET, POST, PUT, PATCH, DELETE)\n- Return 201 on creation, 204 on deletion\n\n## Error Handling\n- Always return JSON `{detail: string}` on errors\n- Use 400 for validation errors, 404 for not found, 422 for business rule violations\n\n## Pagination\n- All list endpoints accept `limit` and `offset`\n- Return `{items, count, total}`"),
    ("eng-hub", None, "On-Call Runbook",
     "# On-Call Runbook\n\n## Alert Tiers\n- **P0**: Service down → page immediately\n- **P1**: Major feature broken → respond within 30min\n- **P2**: Degraded performance → respond within 2h\n\n## Common Issues\n\n### DB Connection Pool Exhausted\n1. Check `pg_stat_activity`\n2. Kill idle connections: `SELECT pg_terminate_backend(pid) WHERE state='idle' AND query_start < now() - interval '10 minutes'`\n3. Restart the app pod\n\n### High Memory Usage\n1. Check if any batch job is running\n2. Review Redis memory: `redis-cli info memory`"),
    ("eng-hub", None, "Code Review Standards",
     "# Code Review Standards\n\n## What to Check\n- No secrets or credentials in code\n- All new endpoints have auth guards\n- SQL queries use parameterization (no f-strings)\n- Edge cases handled (null, empty list, etc.)\n- Tests included for non-trivial logic\n\n## Response Times\n- Minor PRs: review within 24h\n- Major PRs: review within 48h\n\n## PR Size\n- Keep PRs under 400 lines changed\n- Split large features into multiple PRs"),
    # Product & Design
    ("product", None, "Product Roadmap Q2 2026",
     "# Q2 2026 Roadmap\n\n## Themes\n1. **AI Command Center** – EOS agent becomes primary interface\n2. **Developer Experience** – Faster ticket creation, better search\n3. **Analytics** – Client health, velocity trends, capacity planning\n\n## Key Milestones\n| Month | Milestone |\n|-------|-----------|\n| Apr   | EOS agent v2, My Work page |\n| May   | Analytics dashboard, Space health |\n| Jun   | Client portal beta, Test management |"),
    ("product", None, "User Research: Ticket Management Pain Points",
     "# User Research Findings\n\n## Methodology\nInterviewed 8 engineers and 3 EMs over 2 weeks.\n\n## Top Pain Points\n1. Context switching between Jira and Slack (100% mentioned)\n2. Status updates require manual effort (88%)\n3. Hard to see who is blocked and why (75%)\n4. Sprint velocity calculation is opaque (63%)\n\n## Opportunities\n- Auto-status update from git commits\n- Blocker detection via standup parsing\n- Visual burndown with anomaly highlights"),
    ("product", None, "Design System: Component Library",
     "# Component Library\n\n## Primitives\n- `Button` – variants: primary, secondary, ghost, danger\n- `Badge` – variants: status-based colors\n- `Card` – with optional header/footer\n- `Modal` / `Drawer` – for detail panels\n\n## Data Display\n- `DataTable` – sortable, filterable, paginated\n- `KpiCard` – metric + trend + icon\n- `SparklineChart` – inline trend visualization\n\n## Forms\n- `TextInput`, `Select`, `DatePicker`, `MultiSelect`\n- All form components support error states"),
    # Onboarding
    ("onboarding", None, "New Engineer Checklist",
     "# New Engineer Onboarding Checklist\n\n## Week 1\n- [ ] Set up development environment\n- [ ] Read system architecture overview\n- [ ] Complete first ticket (good first issue)\n- [ ] Attend team standup\n- [ ] Meet your buddy engineer\n\n## Week 2\n- [ ] Submit first PR\n- [ ] Review codebase for your pod\n- [ ] Attend sprint planning\n- [ ] Read API design guidelines\n\n## Week 4\n- [ ] Lead a ticket independently\n- [ ] Contribute to team retrospective"),
    ("onboarding", None, "Engineering Culture & Values",
     "# Engineering Culture\n\n## Core Values\n1. **Transparency first** – share blockers early, communicate in the open\n2. **Ship small, ship often** – prefer incremental delivery\n3. **Own your quality** – tests are part of the ticket, not an afterthought\n4. **Help each other** – unblock teammates before picking up new work\n\n## Meeting Norms\n- No meetings on Friday afternoons (deep work time)\n- All decisions documented as ADRs\n- Standups are async-first (use Trackly standup feature)"),
    # Client Docs
    ("clients", None, "Accenture — SLA Agreement",
     "# Accenture SLA\n\n## Uptime Commitment\n- **Target**: 99.5% monthly uptime\n- **Measurement**: Excluding scheduled maintenance\n\n## Response Times\n| Severity | First Response | Resolution |\n|----------|---------------|------------|\n| Critical | 1 hour        | 4 hours    |\n| High     | 4 hours       | 24 hours   |\n| Medium   | 1 business day| 5 business days |\n| Low      | 3 business days| 10 business days |\n\n## Escalation Path\n1. On-call engineer\n2. Tech lead (Abhishek Jain)\n3. Account manager"),
    ("clients", None, "TechCorp — Integration Guide",
     "# TechCorp Integration Guide\n\n## Authentication\nTechCorp uses OAuth 2.0 with client credentials flow.\n\n```\nPOST https://auth.techcorp.com/oauth/token\nContent-Type: application/x-www-form-urlencoded\ngrant_type=client_credentials&client_id=XXX&client_secret=YYY\n```\n\n## Webhooks\nTechCorp sends events to our webhook endpoint:\n`POST /api/webhooks/techcorp`\n\nPayload format: JSON with `event_type`, `timestamp`, `data`.\n\n## Rate Limits\n- 1000 requests/hour per API key\n- Retry with exponential backoff on 429"),
]

page_ids = {}
for slug, parent_title, title, content in WIKI_PAGES:
    space_id = ws_ids.get(slug)
    if not space_id:
        continue
    parent_id = page_ids.get(parent_title) if parent_title else None
    author = random.choice(list(USERS.values()))
    pid = uid()
    page_ids[title] = pid
    cur.execute("""
        INSERT INTO wiki_pages (id, org_id, space_id, parent_id, title, content_md, version, author_id, is_deleted, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,1,%s,false,%s,%s)
    """, (pid, ORG, space_id, parent_id, title, content, author,
          now() - timedelta(days=random.randint(1, 30)), now() - timedelta(days=random.randint(0, 5))))

conn.commit()
print(f"   Created {len(WIKI_PAGES)} wiki pages in {len(WIKI_SPACES)} spaces")

# ─── 9. GOALS / OKRs ────────────────────────────────────────────────────────
print("9. Creating goals...")
# Clear old test goal
cur.execute("DELETE FROM goals WHERE org_id=%s", (ORG,))

GOALS = [
    {
        "quarter": "Q2-2026",
        "title": "Achieve 95% sprint delivery rate across all pods",
        "description": "Improve predictability by reducing scope creep and blocked tickets",
        "owner": "Anoop Rai",
        "status": "on_track",
        "overall_progress": 68,
        "key_results": [
            {"id": uid(), "title": "Reduce blocked tickets from 12% to under 5%", "current": 7, "target": 5, "unit": "%", "linked_tickets": ["DPAI-20", "NOVA-12"], "status": "on_track"},
            {"id": uid(), "title": "Complete 90%+ of sprint commitments for 3 consecutive sprints", "current": 2, "target": 3, "unit": "sprints", "linked_tickets": [], "status": "on_track"},
            {"id": uid(), "title": "Cut average cycle time from 8 days to 5 days", "current": 6.5, "target": 5, "unit": "days", "linked_tickets": [], "status": "at_risk"},
        ],
        "linked_sprints": [EXISTING_SPRINT_ID, sprint_ids["NOVA"]],
        "nova_insight": "Pod DPAI is on track. NOVA shows 2 blocked tickets that may impact sprint completion. Consider reviewing NOVA-12 dependency.",
    },
    {
        "quarter": "Q2-2026",
        "title": "Ship EOS AI Agent v2 with 80% accuracy on ticket recommendations",
        "description": "Upgrade the Nova AI to provide actionable recommendations with measurable accuracy",
        "owner": "Seva Srinivasan",
        "status": "on_track",
        "overall_progress": 55,
        "key_results": [
            {"id": uid(), "title": "Deploy semantic search with >90% relevance score", "current": 87, "target": 90, "unit": "%", "linked_tickets": ["NOVA-1"], "status": "at_risk"},
            {"id": uid(), "title": "My Work page AI rankings validated by 80% of engineers", "current": 60, "target": 80, "unit": "%", "linked_tickets": [], "status": "on_track"},
            {"id": uid(), "title": "Knowledge gap detection covers 100% of active pods", "current": 4, "target": 4, "unit": "pods", "linked_tickets": [], "status": "complete"},
        ],
        "linked_sprints": [sprint_ids["NOVA"]],
        "nova_insight": "Semantic search relevance is at 87%, close to target. Main gap is engineer adoption of My Work recommendations.",
    },
    {
        "quarter": "Q2-2026",
        "title": "Achieve PCI-DSS Level 1 compliance for AURA payment module",
        "description": "Complete all compliance requirements before Q3 client go-live",
        "owner": "Abhishek Jain",
        "status": "at_risk",
        "overall_progress": 40,
        "key_results": [
            {"id": uid(), "title": "Complete all 12 PCI-DSS requirement controls", "current": 5, "target": 12, "unit": "controls", "linked_tickets": ["AURA-1"], "status": "behind"},
            {"id": uid(), "title": "Pass external security audit with zero critical findings", "current": 0, "target": 1, "unit": "audit", "linked_tickets": [], "status": "on_track"},
            {"id": uid(), "title": "Deploy 3D Secure authentication", "current": 0, "target": 1, "unit": "feature", "linked_tickets": ["AURA-2"], "status": "on_track"},
        ],
        "linked_sprints": [sprint_ids["AURA"]],
        "nova_insight": "PCI compliance is behind schedule. 7 controls remain with only 6 weeks left. Risk: FinanceGroup go-live may be delayed.",
    },
    {
        "quarter": "Q2-2026",
        "title": "Launch PULSE client portal with 3 enterprise clients onboarded",
        "description": "Deliver the client-facing portal and complete onboarding for first wave of clients",
        "owner": "Anoop Rai",
        "status": "on_track",
        "overall_progress": 72,
        "key_results": [
            {"id": uid(), "title": "Client portal MVP shipped to production", "current": 1, "target": 1, "unit": "milestone", "linked_tickets": ["PULSE-2"], "status": "on_track"},
            {"id": uid(), "title": "Onboard 3 enterprise clients (RetailCo, HealthFirst, one TBD)", "current": 1, "target": 3, "unit": "clients", "linked_tickets": [], "status": "on_track"},
            {"id": uid(), "title": "Event pipeline processes 1M events/day without degradation", "current": 650000, "target": 1000000, "unit": "events/day", "linked_tickets": ["PULSE-1"], "status": "on_track"},
        ],
        "linked_sprints": [sprint_ids["PULSE"]],
        "nova_insight": "Strong progress on event pipeline. Client onboarding is the key risk — RetailCo onboarded, 2 more needed.",
    },
    {
        "quarter": "Q2-2026",
        "title": "Reduce bug rate by 40% through test automation",
        "description": "Invest in test coverage to reduce production incidents and improve confidence",
        "owner": "Seva Srinivasan",
        "status": "behind",
        "overall_progress": 30,
        "key_results": [
            {"id": uid(), "title": "Achieve 70% unit test coverage across all pods", "current": 45, "target": 70, "unit": "%", "linked_tickets": [], "status": "behind"},
            {"id": uid(), "title": "Create test cycles for all active releases", "current": 1, "target": 4, "unit": "cycles", "linked_tickets": [], "status": "behind"},
            {"id": uid(), "title": "Zero P0 bugs in production for 4 consecutive weeks", "current": 2, "target": 4, "unit": "weeks", "linked_tickets": [], "status": "on_track"},
        ],
        "linked_sprints": [],
        "nova_insight": "Test coverage is significantly behind target. Recommend allocating 20% of each sprint to test work.",
    },
    {
        "quarter": "Q1-2026",
        "title": "Establish team health baseline and reduce burnout risk",
        "description": "Use analytics and 1:1s to identify and address team health issues",
        "owner": "Anoop Rai",
        "status": "complete",
        "overall_progress": 100,
        "key_results": [
            {"id": uid(), "title": "Weekly 1:1 cadence established for all engineers", "current": 12, "target": 12, "unit": "engineers", "linked_tickets": [], "status": "complete"},
            {"id": uid(), "title": "Team NPS score above 7.0", "current": 7.4, "target": 7.0, "unit": "score", "linked_tickets": [], "status": "complete"},
            {"id": uid(), "title": "Overtime hours reduced by 30%", "current": 32, "target": 30, "unit": "%", "linked_tickets": [], "status": "complete"},
        ],
        "linked_sprints": [],
        "nova_insight": "Goal completed in Q1. Team NPS improved from 6.1 to 7.4. Continue monitoring in Q2.",
    },
]

for g in GOALS:
    cur.execute("""
        INSERT INTO goals (id, org_id, quarter, title, description, owner, status, overall_progress,
                           key_results, linked_sprints, nova_insight, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (uid(), ORG, g["quarter"], g["title"], g["description"], g["owner"],
          g["status"], g["overall_progress"],
          json.dumps(g["key_results"]),
          json.dumps(g["linked_sprints"]),
          g.get("nova_insight"),
          now() - timedelta(days=random.randint(10, 30)), now()))

conn.commit()
print(f"   Created {len(GOALS)} goals")

# ─── 10. DECISIONS (ADRs) ────────────────────────────────────────────────────
print("10. Creating decisions (ADRs)...")
cur.execute("DELETE FROM decisions WHERE org_id=%s", (ORG,))

DECISIONS = [
    (1, "Use PostgreSQL with pgvector for semantic search", "accepted", "Anoop Rai", "2025-11-10",
     "We needed vector search for ticket and wiki semantic similarity. Evaluated Pinecone, Weaviate, and pgvector.",
     "Use pgvector extension on PostgreSQL 15 for embedding storage and ANN search.",
     "pgvector integrates with our existing Postgres, avoids another service to manage, and meets our p99 latency requirements (<200ms).",
     ["Pinecone (SaaS, expensive at scale)", "Weaviate (good but another service to run)", "Elasticsearch with dense vector (complex)"],
     "We are locked into Postgres for vector search. If we need sub-10ms latency at 100M+ vectors, we will need to revisit.",
     ["NOVA-1"], ["architecture", "search", "database"], True),
    (2, "JWT with refresh tokens for authentication (no sessions)", "accepted", "Seva Srinivasan", "2025-10-20",
     "Needed stateless auth that works across API and frontend without sticky sessions.",
     "Use short-lived JWT access tokens (15min) + long-lived refresh tokens (7 days) stored in httpOnly cookies.",
     "Stateless auth enables horizontal scaling. httpOnly cookies mitigate XSS. Refresh tokens allow session revocation.",
     ["Server-side sessions with Redis", "OAuth only (too complex for internal tool)", "Long-lived JWTs (security risk)"],
     "Must implement token revocation list (Redis) for logout and compromised token scenarios.",
     [], ["architecture", "security", "auth"], True),
    (3, "FastAPI over Django REST Framework", "accepted", "Abhishek Jain", "2025-09-15",
     "Choosing the backend framework for the Trackly API.",
     "Use FastAPI for all API development.",
     "FastAPI's async support, automatic OpenAPI docs, and Pydantic integration reduce boilerplate significantly. 3x faster than DRF in benchmarks.",
     ["Django REST Framework (more batteries, heavier)", "Flask (too minimal, no async)", "Node.js/Express (team is Python-first)"],
     "Less ecosystem maturity than Django for admin tools. Accept this tradeoff.",
     [], ["architecture", "backend"], True),
    (4, "React Query (TanStack Query) for server state management", "accepted", "Anand Verma", "2025-09-20",
     "Needed a solution for server state (API data) management, distinct from UI state.",
     "Use TanStack Query for all API calls and cache management in the React frontend.",
     "Reduces boilerplate for loading/error states, automatic cache invalidation, and background refetching.",
     ["Redux Toolkit Query (more Redux complexity)", "SWR (simpler but less featured)", "Plain useEffect (too much manual work)"],
     "Team needs to learn TanStack Query mental model (staleTime, invalidation).",
     [], ["architecture", "frontend"], True),
    (5, "Multi-tenant via org_id column (not schema-per-tenant)", "accepted", "Seva Srinivasan", "2025-10-05",
     "Designing multi-tenancy for the Trackly SaaS model.",
     "Use org_id column on every table with row-level security enforced at the application layer.",
     "Simpler to manage than schema-per-tenant. Row-level security in application layer is sufficient for current scale.",
     ["Schema-per-tenant (better isolation, complex migrations)", "Separate DB per tenant (expensive)"],
     "Application must ALWAYS filter by org_id. A bug here would be a critical data leak. Mitigated by base query helpers.",
     [], ["architecture", "database", "security"], True),
    (6, "Deprecate XML API format by June 2026", "proposed", "Akash Kumar", "2026-04-01",
     "The TechCorp integration uses XML responses. All new clients use JSON. Maintaining both is costly.",
     "Deprecate XML response format in the API gateway by June 30, 2026.",
     "Reduces maintenance burden and allows removing the XML serialization layer.",
     ["Keep XML indefinitely (ongoing cost)", "Provide XML-to-JSON migration service for TechCorp"],
     "TechCorp must migrate their integration before June 30. Risk: contract SLA violation if they miss the deadline.",
     ["NOVA-15"], ["api", "deprecation"], False),
    (7, "Use Alembic for all DB migrations (no manual SQL)", "accepted", "Abhishek Jain", "2025-10-01",
     "Needed a consistent approach to database schema changes.",
     "All schema changes must go through Alembic migration files. No manual SQL in production.",
     "Ensures all environments stay in sync and changes are versioned and reversible.",
     ["Manual SQL scripts (error-prone)", "Liquibase (Java dependency)"],
     "Team must remember to create migrations before deploying. CI/CD pipeline checks for pending migrations.",
     [], ["database", "process"], True),
    (8, "Redis for caching and task queues (not Celery+RabbitMQ)", "accepted", "Nihar Bansal", "2025-11-20",
     "Needed caching for expensive queries and async task processing for background jobs.",
     "Use Redis for both caching (TTL-based) and as a simple task queue with rq (Redis Queue).",
     "Simpler stack than Celery+RabbitMQ. Redis is already used for refresh token storage.",
     ["Celery + RabbitMQ (powerful but complex)", "In-process threading (not scalable)", "SQS + Lambda (cloud vendor lock-in)"],
     "rq is less feature-rich than Celery. Accept this for current scale. Revisit at 100K tasks/day.",
     [], ["architecture", "infrastructure"], True),
]

for num, title, status, owner, ddate, context, decision, rationale, alts, consequences, linked, tags, org_level in DECISIONS:
    cur.execute("""
        INSERT INTO decisions (id, org_id, number, title, status, owner, date, context, decision, rationale,
                               alternatives, consequences, linked_tickets, tags, space_id, org_level, is_deleted, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,false,%s,%s)
    """, (uid(), ORG, num, title, status, owner, ddate, context, decision, rationale,
          alts, consequences, linked, tags, org_level, now(), now()))

conn.commit()
print(f"   Created {len(DECISIONS)} decisions")

# ─── 11. PROCESSES (SOPs) ────────────────────────────────────────────────────
print("11. Creating processes...")
cur.execute("DELETE FROM processes WHERE org_id=%s", (ORG,))

PROCS = [
    ("Production Deployment Runbook", "runbook", "active", "Seva Srinivasan",
     "Step-by-step process for deploying to production safely.",
     [{"id": uid(), "order": 1, "title": "Pre-deploy checklist", "description": "Verify all tests pass, migrations are ready, and rollback plan is documented.", "owner": "Tech Lead", "estimatedTime": "15 min", "required": True},
      {"id": uid(), "order": 2, "title": "Announce deploy in #deployments Slack", "description": "Post: 'Deploying v{version} at {time}. ETA: 20 min. Rollback: git revert {sha}'", "owner": "Tech Lead", "estimatedTime": "2 min", "required": True},
      {"id": uid(), "order": 3, "title": "Run database migrations", "description": "ssh to bastion and run: `alembic upgrade head`. Verify with `alembic current`.", "owner": "Engineer", "estimatedTime": "5 min", "required": True},
      {"id": uid(), "order": 4, "title": "Deploy new containers", "description": "Push Docker image and trigger ECS rolling update.", "owner": "Engineer", "estimatedTime": "10 min", "required": True},
      {"id": uid(), "order": 5, "title": "Smoke test in production", "description": "Run smoke test suite against prod: `pytest tests/smoke/ --env=prod`", "owner": "QA", "estimatedTime": "10 min", "required": True},
      {"id": uid(), "order": 6, "title": "Monitor for 20 minutes", "description": "Watch error rate, p99 latency, and memory on Grafana dashboard.", "owner": "On-call", "estimatedTime": "20 min", "required": True}],
     ["deployment", "production", "runbook"], True, "~62 min", 24),

    ("Incident Response Process", "runbook", "active", "Anoop Rai",
     "How to respond to production incidents from detection to post-mortem.",
     [{"id": uid(), "order": 1, "title": "Detect and declare incident", "description": "If alert fires or user reports issue, declare incident in #incidents and assign severity (P0-P3).", "required": True, "estimatedTime": "5 min"},
      {"id": uid(), "order": 2, "title": "Assign Incident Commander", "description": "On-call engineer becomes IC. IC coordinates response, delegates tasks.", "required": True, "estimatedTime": "2 min"},
      {"id": uid(), "order": 3, "title": "Investigate root cause", "description": "Check logs, metrics, recent deploys. Use runbook for common issues.", "required": True, "estimatedTime": "30 min"},
      {"id": uid(), "order": 4, "title": "Implement fix or rollback", "description": "Deploy fix or rollback to last stable version. Announce in #incidents.", "required": True, "estimatedTime": "20 min"},
      {"id": uid(), "order": 5, "title": "Write post-mortem", "description": "Within 48h: document timeline, root cause, impact, and action items in wiki.", "required": True, "estimatedTime": "60 min"}],
     ["incident", "production", "sop"], True, "~2h", 8),

    ("Sprint Planning SOP", "sop", "active", "Abhishek Jain",
     "Standard process for sprint planning ceremony.",
     [{"id": uid(), "order": 1, "title": "Groom backlog 2 days before", "description": "Product owner and tech lead review and estimate top 30 backlog items.", "required": True, "estimatedTime": "60 min"},
      {"id": uid(), "order": 2, "title": "Sprint planning meeting", "description": "Team reviews sprint goal, selects tickets, and assigns owners. Max 2 hours.", "required": True, "estimatedTime": "120 min"},
      {"id": uid(), "order": 3, "title": "Create sprint in Trackly", "description": "Tech lead creates sprint, sets dates, and moves selected tickets into it.", "required": True, "estimatedTime": "10 min"},
      {"id": uid(), "order": 4, "title": "Communicate sprint goal", "description": "Share sprint goal and key tickets in team Slack channel.", "required": True, "estimatedTime": "5 min"}],
     ["sprint", "process", "planning"], True, "~3h", 12),

    ("New Client Onboarding Checklist", "sop", "active", "Anoop Rai",
     "End-to-end checklist for onboarding a new enterprise client.",
     [{"id": uid(), "order": 1, "title": "Technical kickoff call", "description": "Review integration requirements, data formats, and SLA expectations.", "required": True, "estimatedTime": "60 min"},
      {"id": uid(), "order": 2, "title": "Provision client environment", "description": "Create org in Trackly, set up API keys, configure webhook URLs.", "required": True, "estimatedTime": "30 min"},
      {"id": uid(), "order": 3, "title": "Integration testing", "description": "Test data flow end-to-end with client's test environment.", "required": True, "estimatedTime": "4h"},
      {"id": uid(), "order": 4, "title": "Training session", "description": "Run 1-hour training for client's team on Trackly features.", "required": True, "estimatedTime": "60 min"},
      {"id": uid(), "order": 5, "title": "Go-live sign-off", "description": "Get written confirmation from client that integration is working correctly.", "required": True, "estimatedTime": "15 min"}],
     ["client", "onboarding", "sop"], True, "~6h", 3),

    ("Security Incident Compliance Report", "compliance", "active", "Seva Srinivasan",
     "Required process for reporting security incidents per SOC 2 compliance.",
     [{"id": uid(), "order": 1, "title": "Classify the incident", "description": "Determine if incident involves PII, payment data, or credential exposure.", "required": True, "estimatedTime": "15 min"},
      {"id": uid(), "order": 2, "title": "Notify security team within 1 hour", "description": "Email security@3scsolution.com with incident summary.", "required": True, "estimatedTime": "10 min"},
      {"id": uid(), "order": 3, "title": "Preserve evidence", "description": "Take logs, screenshots, and snapshots before any remediation.", "required": True, "estimatedTime": "20 min"},
      {"id": uid(), "order": 4, "title": "Remediate and document", "description": "Fix the vulnerability and document all steps taken.", "required": True, "estimatedTime": "varies"},
      {"id": uid(), "order": 5, "title": "Submit compliance report", "description": "Fill in the SOC 2 incident report template within 72 hours.", "required": True, "estimatedTime": "30 min"}],
     ["compliance", "security", "soc2"], True, "~2h", 1),

    ("Engineering Manager Weekly Review", "workflow", "active", "Anoop Rai",
     "Weekly ritual for EMs to review team health, velocity, and blockers.",
     [{"id": uid(), "order": 1, "title": "Review sprint burndown", "description": "Check if sprint is on track. Flag any tickets that haven't moved in 3+ days.", "required": True, "estimatedTime": "15 min"},
      {"id": uid(), "order": 2, "title": "Review blocked tickets", "description": "Ensure every blocked ticket has an owner working on unblocking it.", "required": True, "estimatedTime": "10 min"},
      {"id": uid(), "order": 3, "title": "Check team sentiment", "description": "Read standup entries for signals of frustration, overload, or confusion.", "required": True, "estimatedTime": "10 min"},
      {"id": uid(), "order": 4, "title": "Update goal progress", "description": "Update OKR progress in Trackly based on completed tickets.", "required": True, "estimatedTime": "15 min"},
      {"id": uid(), "order": 5, "title": "Prepare team update", "description": "Write a 3-bullet team update for the all-hands doc.", "required": False, "estimatedTime": "10 min"}],
     ["management", "workflow", "weekly"], True, "~60 min", 52),
]

for title, cat, status, owner, desc, steps, tags, compliance, avg_time, run_count in PROCS:
    cur.execute("""
        INSERT INTO processes (id, org_id, title, category, status, owner, last_updated, description,
                               steps, tags, compliance_required, avg_completion_time, run_count,
                               space_id, org_level, is_deleted, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NULL,%s,false,%s,%s)
    """, (uid(), ORG, title, cat, status, owner,
          days_ago(random.randint(1, 30)), desc,
          json.dumps(steps), tags, compliance, avg_time, run_count, True, now(), now()))

conn.commit()
print(f"   Created {len(PROCS)} processes")

# ─── 12. KNOWLEDGE GAPS ──────────────────────────────────────────────────────
print("12. Creating knowledge gaps...")
cur.execute("DELETE FROM knowledge_gaps WHERE org_id=%s", (ORG,))
GAPS = [
    ("Redis Queue job failure handling", 8, 0, "NOVA-9,NOVA-3", "Create wiki page documenting retry strategies and dead-letter queue patterns for rq jobs."),
    ("PCI-DSS 3D Secure implementation", 5, 0, "AURA-1,AURA-2", "Document the 3DS authentication flow and PCI compliance requirements in the Engineering Hub."),
    ("Event schema versioning in Kafka", 6, 0, "PULSE-11,PULSE-1", "No documentation on how to evolve Kafka event schemas without breaking consumers."),
    ("pgvector performance tuning", 4, 0, "NOVA-1,NOVA-12", "IVFFlat index parameters and HNSW tradeoffs are undocumented. Engineers are guessing at configuration."),
    ("Multi-currency decimal handling", 3, 0, "AURA-3,AURA-16", "AURA team keeps hitting rounding bugs. Need a canonical guide on decimal arithmetic for financial data."),
]
for topic, ticket_count, wiki_cov, examples, suggestion in GAPS:
    cur.execute("""
        INSERT INTO knowledge_gaps (id, org_id, topic, ticket_count, wiki_coverage, example_tickets, suggestion, detected_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (uid(), ORG, topic, ticket_count, wiki_cov, examples, suggestion, now() - timedelta(days=random.randint(0, 7))))

conn.commit()
print(f"   Created {len(GAPS)} knowledge gaps")

# ─── 13. CLIENT BUDGETS ──────────────────────────────────────────────────────
print("13. Creating client budgets...")
cur.execute("DELETE FROM client_budgets WHERE org_id=%s", (ORG,))
today = date.today()
BUDGETS = [
    ("Accenture",     160, 118, "on_track"),
    ("TechCorp",      120,  98, "warning"),
    ("FinanceGroup",  200, 185, "critical"),
    ("RetailCo",       80,  45, "on_track"),
    ("HealthFirst",   100,  22, "on_track"),
]
for client, budget, used, status in BUDGETS:
    cur.execute("""
        INSERT INTO client_budgets (id, org_id, client, month, year, budget_hours, hours_used, burn_pct, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (uid(), ORG, client, today.month, today.year, budget, used,
          round(used / budget * 100, 1), status))

conn.commit()
print(f"   Created {len(BUDGETS)} client budgets")

# ─── 14. TEST CASES ──────────────────────────────────────────────────────────
print("14. Creating test cases and cycles...")

TEST_CASES = {
    "DPAI": [
        ("Dashboard loads within 3 seconds",
         "Verify the main dashboard renders within the SLA",
         [{"step": "Open the dashboard URL", "expected_result": "Page starts loading"},
          {"step": "Measure time to interactive", "expected_result": "Less than 3000ms"},
          {"step": "Check all widgets render", "expected_result": "No broken widget states"}], "high"),
        ("Date filter updates all charts",
         "Verify date filter change propagates to all dashboard charts",
         [{"step": "Set date range to last 7 days", "expected_result": "All charts refresh"},
          {"step": "Check ticket count card updates", "expected_result": "Count matches filter"},
          {"step": "Export data with filter active", "expected_result": "Export respects filter"}], "medium"),
        ("Dark mode persists on reload",
         "User dark mode preference is remembered",
         [{"step": "Enable dark mode in settings", "expected_result": "UI switches to dark theme"},
          {"step": "Reload the page", "expected_result": "Dark mode is still active"},
          {"step": "Clear localStorage and reload", "expected_result": "Falls back to light mode"}], "low"),
    ],
    "NOVA": [
        ("Semantic search returns relevant results",
         "Test that semantic search returns contextually relevant tickets",
         [{"step": "Search for 'payment processing error'", "expected_result": "Results include AURA payment-related tickets"},
          {"step": "Check relevance scores", "expected_result": "Top result has score > 0.8"},
          {"step": "Click a result", "expected_result": "Ticket detail opens correctly"}], "high"),
        ("Real-time notification delivered under 2s",
         "Verify WebSocket notifications arrive promptly",
         [{"step": "Open app in two browser tabs as different users", "expected_result": "Both tabs connected"},
          {"step": "Assign a ticket to user in tab 2", "expected_result": "Notification appears in tab 2 within 2 seconds"},
          {"step": "Mark notification as read", "expected_result": "Badge count decrements"}], "high"),
    ],
    "AURA": [
        ("Invoice total calculation is accurate",
         "Verify that invoice totals correctly handle decimal rounding",
         [{"step": "Create invoice with 3 line items of fractional amounts", "expected_result": "Total matches sum of line items"},
          {"step": "Apply 8.5% tax", "expected_result": "Tax amount rounds correctly (banker's rounding)"},
          {"step": "Export invoice to PDF", "expected_result": "PDF totals match UI"}], "high"),
        ("3D Secure flow completes successfully",
         "End-to-end test of 3DS authentication for high-risk transactions",
         [{"step": "Initiate payment over $500", "expected_result": "3DS challenge is triggered"},
          {"step": "Complete OTP verification", "expected_result": "Payment proceeds to authorization"},
          {"step": "Check audit log", "expected_result": "3DS outcome is recorded"}], "high"),
    ],
    "PULSE": [
        ("Event pipeline processes 10K events without loss",
         "Load test the event streaming pipeline",
         [{"step": "Send 10,000 events via producer script", "expected_result": "No producer errors"},
          {"step": "Check consumer lag after 60 seconds", "expected_result": "Lag < 1000 events"},
          {"step": "Verify all events in sink DB", "expected_result": "Event count matches 10,000"}], "high"),
        ("Client portal access control enforces tenant isolation",
         "Verify clients cannot see each other's data",
         [{"step": "Log in as RetailCo client user", "expected_result": "Only RetailCo data visible"},
          {"step": "Attempt to access HealthFirst endpoint via direct URL", "expected_result": "403 Forbidden"},
          {"step": "Check audit log", "expected_result": "Unauthorized access attempt logged"}], "high"),
    ],
}

tc_ids = {}  # pod -> [tc_id]
for pod, cases in TEST_CASES.items():
    tc_ids[pod] = []
    for title, desc, steps, priority in cases:
        tcid = uid()
        tc_ids[pod].append(tcid)
        cur.execute("""
            INSERT INTO test_cases (id, org_id, pod, title, description, steps, priority, status, ai_generated, created_by, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'active',false,%s,%s,%s)
        """, (tcid, ORG, pod, title, desc, json.dumps(steps), priority,
              POD_LEAD[pod], now() - timedelta(days=random.randint(1, 10)), now()))

conn.commit()

# Test cycles and executions
for pod in PODS:
    if not tc_ids.get(pod):
        continue
    active_sprint = sprint_ids[pod]
    release_list  = release_ids.get(pod, [None])
    cycle_id = uid()
    cur.execute("""
        INSERT INTO test_cycles (id, org_id, pod, name, description, sprint_id, release_id, status, created_by, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)
    """, (cycle_id, ORG, pod,
          f"{pod} — Sprint 3 Test Cycle",
          f"QA cycle for {pod} Sprint 3 tickets",
          active_sprint,
          release_list[min(1, len(release_list)-1)] if len(release_list) > 1 else release_list[0],
          POD_LEAD[pod], now(), now()))

    EXEC_STATUSES = ["pending", "passed", "failed", "passed", "passed"]
    for tc_id in tc_ids[pod]:
        exec_status = random.choice(EXEC_STATUSES)
        cur.execute("""
            INSERT INTO test_executions (id, cycle_id, test_case_id, status, executed_by, notes, executed_at, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (uid(), cycle_id, tc_id, exec_status,
              random.choice(POD_ENGINEERS.get(pod, ENGINEERS)),
              "All steps verified." if exec_status == "passed" else "Step 2 failed: unexpected result.",
              now() - timedelta(hours=random.randint(1, 48)),
              now() - timedelta(days=2), now()))

conn.commit()
print(f"   Created test cases and cycles for all pods")

# ─── 15. SPACE MEMBERS ───────────────────────────────────────────────────────
print("15. Creating space members...")
cur.execute("DELETE FROM space_members WHERE org_id=%s", (ORG,))
for pod, engineers in POD_ENGINEERS.items():
    lead = POD_LEAD[pod]
    all_members = engineers + [lead]
    for name in all_members:
        uid_val = USERS.get(name)
        if not uid_val:
            continue
        cur.execute("""
            INSERT INTO space_members (id, org_id, pod, user_id, role, joined_at)
            VALUES (%s,%s,%s,%s,%s,%s)
            ON CONFLICT DO NOTHING
        """, (uid(), ORG, pod, uid_val,
              "lead" if name == lead else "member",
              now() - timedelta(days=random.randint(30, 90))))

conn.commit()
print("   Space members linked")

# ─── 16. BOARD CONFIGS ───────────────────────────────────────────────────────
print("16. Creating board configs...")
cur.execute("DELETE FROM board_configs WHERE org_id=%s", (ORG,))
DEFAULT_COLUMNS = [
    {"id": "backlog",     "title": "Backlog",     "status": "Backlog",     "color": "#6b7280", "limit": None},
    {"id": "todo",        "title": "To Do",        "status": "To Do",       "color": "#3b82f6", "limit": 10},
    {"id": "in_progress", "title": "In Progress",  "status": "In Progress", "color": "#f59e0b", "limit": 5},
    {"id": "in_review",   "title": "In Review",    "status": "In Review",   "color": "#8b5cf6", "limit": 5},
    {"id": "done",        "title": "Done",          "status": "Done",        "color": "#10b981", "limit": None},
    {"id": "blocked",     "title": "Blocked",       "status": "Blocked",     "color": "#ef4444", "limit": None},
]
for pod in PODS:
    cur.execute("""
        INSERT INTO board_configs (id, org_id, pod, columns, updated_at)
        VALUES (%s,%s,%s,%s,%s)
        ON CONFLICT (org_id, pod) DO UPDATE SET columns=EXCLUDED.columns, updated_at=EXCLUDED.updated_at
    """, (uid(), ORG, pod, json.dumps(DEFAULT_COLUMNS), now()))

conn.commit()
print("   Board configs created")

# ─── 17. AUTOMATION RULES ────────────────────────────────────────────────────
print("17. Creating automation rules...")
cur.execute("DELETE FROM automation_rules WHERE org_id=%s", (ORG,))
AUTOMATIONS = [
    ("DPAI", "Auto-assign blocked tickets to lead", "status_change", "status_is", {"status": "Blocked"},
     "assign_to", {"user_id": USERS["Abhishek Jain"]}, "Abhishek Jain"),
    ("NOVA", "Label high-priority bugs as urgent", "ticket_created", "priority_is", {"priority": "Highest"},
     "add_label", {"label": "urgent"}, "Anoop Rai"),
    ("AURA", "Auto-move Done tickets out of sprint", "status_change", "status_is", {"status": "Done"},
     "post_comment", {"comment_body": "✅ Ticket completed. Will be removed from sprint on next planning."}, "Seva Srinivasan"),
    ("PULSE", "Create subtask for QA on story completion", "status_change", "status_is", {"status": "In Review"},
     "create_subtask", {"subtask_summary": "QA verification"}, "Anoop Rai"),
]
for pod, name, trigger, cond_type, cond_cfg, action_type, action_cfg, created_by_name in AUTOMATIONS:
    cur.execute("""
        INSERT INTO automation_rules (id, org_id, pod, name, trigger_type, condition_type, condition_config,
                                       action_type, action_config, is_active, run_count, created_by, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,0,%s,%s)
    """, (uid(), ORG, pod, name, trigger, cond_type, json.dumps(cond_cfg),
          action_type, json.dumps(action_cfg), USERS.get(created_by_name), now()))

conn.commit()
print(f"   Created {len(AUTOMATIONS)} automation rules")

# ─── 18. NOTIFICATIONS ───────────────────────────────────────────────────────
print("18. Creating notifications...")
user_ids = list(USERS.values())[1:]  # skip admin
NOTIF_TEMPLATES = [
    ("ticket_assigned",    "Ticket assigned to you",         "DPAI-5 has been assigned to you",                 "/tickets?key=DPAI-5"),
    ("sprint_started",     "Sprint started",                  "DPAI — Sprint 3 has started. 14 tickets assigned.", "/spaces/DPAI"),
    ("ticket_done",        "Ticket completed",               "NOVA-8 marked as Done",                            "/tickets?key=NOVA-8"),
    ("blocked_ticket",     "Ticket is blocked",              "AURA-15 is now blocked. Action needed.",           "/tickets?key=AURA-15"),
    ("burn_rate_alert",    "Budget warning for FinanceGroup", "FinanceGroup has used 92.5% of monthly budget",   "/settings"),
    ("ticket_in_review",   "PR ready for review",            "PULSE-6 is now In Review. Your input needed.",    "/tickets?key=PULSE-6"),
    ("mention",            "You were mentioned",             "@anand mentioned you in NOVA-4 comment",           "/tickets?key=NOVA-4"),
]
for i, uid_val in enumerate(user_ids[:6]):
    ttype, title, body, link = NOTIF_TEMPLATES[i % len(NOTIF_TEMPLATES)]
    cur.execute("""
        INSERT INTO notifications (id, org_id, user_id, type, title, body, link, is_read, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (uid(), ORG, uid_val, ttype, title, body, link,
          random.random() < 0.4, now() - timedelta(hours=random.randint(1, 72))))

conn.commit()
print("   Notifications created")

# ─── DONE ─────────────────────────────────────────────────────────────────────
cur.close()
conn.close()
print()
print("=== Seed complete! ===")
print("Summary:")
print(f"  Pods:          {', '.join(PODS)}")
print(f"  Tickets:       {sum(len(t) for t in TICKET_TEMPLATES.values())} (+ 2 existing)")
print(f"  Sprints:       {len(PODS) * 3} total (1 active + 2 completed per pod)")
print(f"  Epics:         Created/updated for all pods")
print(f"  Wiki spaces:   {len(WIKI_SPACES)}")
print(f"  Wiki pages:    {len(WIKI_PAGES)}")
print(f"  Goals:         {len(GOALS)}")
print(f"  Decisions:     {len(DECISIONS)}")
print(f"  Processes:     {len(PROCS)}")
print(f"  Releases:      {sum(len(v) for v in RELEASE_DEFS.values())}")
print(f"  Test cases:    {sum(len(v) for v in TEST_CASES.values())}")
print(f"  Client budgets:{len(BUDGETS)}")
print(f"  Notifications: 6")
