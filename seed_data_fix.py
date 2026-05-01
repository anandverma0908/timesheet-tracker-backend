"""
seed_data_fix.py — Fix the remaining sections that failed in seed_data.py
Runs sections 13-18 only (1-12 already committed).
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
PODS = ["DPAI", "NOVA", "AURA", "PULSE"]
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

# Reload sprint_ids and release_ids from DB
cur.execute("SELECT pod, id FROM sprints WHERE status='active' AND org_id=%s", (ORG,))
sprint_ids = {row[0]: row[1] for row in cur.fetchall()}

cur.execute("SELECT pod, array_agg(id ORDER BY created_at) FROM releases WHERE org_id=%s GROUP BY pod", (ORG,))
release_ids = {row[0]: row[1] for row in cur.fetchall()}

# ─── 13. CLIENT BUDGETS ──────────────────────────────────────────────────────
print("13. Creating client budgets...")
cur.execute("DELETE FROM client_budgets WHERE org_id=%s", (ORG,))
today = date.today()
BUDGETS = [
    ("Accenture",     160),
    ("TechCorp",      120),
    ("FinanceGroup",  200),
    ("RetailCo",       80),
    ("HealthFirst",   100),
]
for client, budget in BUDGETS:
    cur.execute("""
        INSERT INTO client_budgets (id, org_id, client, month, year, budget_hours)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (org_id, client, month, year) DO UPDATE SET budget_hours=EXCLUDED.budget_hours
    """, (uid(), ORG, client, today.month, today.year, budget))

conn.commit()
print(f"   Created {len(BUDGETS)} client budgets")

# ─── 14. TEST CASES ──────────────────────────────────────────────────────────
print("14. Creating test cases and cycles...")
# Clear existing ones from prior run
cur.execute("DELETE FROM test_executions WHERE cycle_id IN (SELECT id FROM test_cycles WHERE org_id=%s)", (ORG,))
cur.execute("DELETE FROM test_cycles WHERE org_id=%s", (ORG,))
cur.execute("DELETE FROM test_cases WHERE org_id=%s", (ORG,))

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
          {"step": "Reload the page", "expected_result": "Dark mode is still active"}], "low"),
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
          {"step": "Assign a ticket to user in tab 2", "expected_result": "Notification appears within 2 seconds"},
          {"step": "Mark notification as read", "expected_result": "Badge count decrements"}], "high"),
    ],
    "AURA": [
        ("Invoice total calculation is accurate",
         "Verify that invoice totals correctly handle decimal rounding",
         [{"step": "Create invoice with 3 line items of fractional amounts", "expected_result": "Total matches sum"},
          {"step": "Apply 8.5% tax", "expected_result": "Tax amount rounds correctly"},
          {"step": "Export invoice to PDF", "expected_result": "PDF totals match UI"}], "high"),
        ("3D Secure flow completes successfully",
         "End-to-end test of 3DS authentication for high-risk transactions",
         [{"step": "Initiate payment over $500", "expected_result": "3DS challenge triggered"},
          {"step": "Complete OTP verification", "expected_result": "Payment proceeds to authorization"},
          {"step": "Check audit log", "expected_result": "3DS outcome is recorded"}], "high"),
    ],
    "PULSE": [
        ("Event pipeline processes 10K events without loss",
         "Load test the event streaming pipeline",
         [{"step": "Send 10,000 events via producer script", "expected_result": "No producer errors"},
          {"step": "Check consumer lag after 60 seconds", "expected_result": "Lag < 1000 events"},
          {"step": "Verify all events in sink DB", "expected_result": "Event count matches 10,000"}], "high"),
        ("Client portal enforces tenant isolation",
         "Verify clients cannot see each other's data",
         [{"step": "Log in as RetailCo client user", "expected_result": "Only RetailCo data visible"},
          {"step": "Attempt to access HealthFirst endpoint directly", "expected_result": "403 Forbidden"}], "high"),
    ],
}

tc_ids = {}
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

EXEC_STATUSES = ["pending", "passed", "failed", "passed", "passed"]
for pod in PODS:
    if not tc_ids.get(pod):
        continue
    active_sprint = sprint_ids.get(pod)
    releases_for_pod = release_ids.get(pod, [])
    release_id = releases_for_pod[1] if len(releases_for_pod) > 1 else (releases_for_pod[0] if releases_for_pod else None)

    cycle_id = uid()
    cur.execute("""
        INSERT INTO test_cycles (id, org_id, pod, name, description, sprint_id, release_id, status, created_by, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)
    """, (cycle_id, ORG, pod,
          f"{pod} — Sprint 3 Test Cycle",
          f"QA cycle for {pod} Sprint 3 tickets",
          active_sprint, str(release_id) if release_id else None,
          POD_LEAD[pod], now(), now()))

    for tc_id in tc_ids[pod]:
        exec_status = random.choice(EXEC_STATUSES)
        cur.execute("""
            INSERT INTO test_executions (id, cycle_id, test_case_id, status, executed_by, notes, executed_at, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (uid(), cycle_id, tc_id, exec_status,
              random.choice(POD_ENGINEERS.get(pod, [])),
              "All steps verified." if exec_status == "passed" else "Step 2 failed.",
              now() - timedelta(hours=random.randint(1, 48)),
              now() - timedelta(days=2), now()))

conn.commit()
print(f"   Created test cases and cycles for all pods")

# ─── 15. SPACE MEMBERS ───────────────────────────────────────────────────────
print("15. Creating space members...")
cur.execute("DELETE FROM space_members WHERE org_id=%s", (ORG,))
for pod, engineers in POD_ENGINEERS.items():
    lead = POD_LEAD[pod]
    for name in engineers + [lead]:
        uid_val = USERS.get(name)
        if not uid_val:
            continue
        ts = now() - timedelta(days=random.randint(30, 90))
        cur.execute("""
            INSERT INTO space_members (id, org_id, pod, user_id, role, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (org_id, pod, user_id) DO NOTHING
        """, (uid(), ORG, pod, uid_val,
              "lead" if name == lead else "member", ts, ts))

conn.commit()
print("   Space members linked")

# ─── 16. BOARD CONFIGS ───────────────────────────────────────────────────────
print("16. Creating board configs...")
cur.execute("DELETE FROM board_configs WHERE org_id=%s", (ORG,))
COLUMNS = [
    {"id": "backlog",     "title": "Backlog",      "status": "Backlog",     "color": "#6b7280"},
    {"id": "todo",        "title": "To Do",         "status": "To Do",       "color": "#3b82f6"},
    {"id": "in_progress", "title": "In Progress",   "status": "In Progress", "color": "#f59e0b"},
    {"id": "in_review",   "title": "In Review",     "status": "In Review",   "color": "#8b5cf6"},
    {"id": "done",        "title": "Done",           "status": "Done",        "color": "#10b981"},
    {"id": "blocked",     "title": "Blocked",        "status": "Blocked",     "color": "#ef4444"},
]
WIP = {"in_progress": 5, "in_review": 5}
for pod in PODS:
    cur.execute("""
        INSERT INTO board_configs (id, org_id, pod, columns, wip_limits, created_at)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (org_id, pod) DO UPDATE SET columns=EXCLUDED.columns, wip_limits=EXCLUDED.wip_limits
    """, (uid(), ORG, pod, json.dumps(COLUMNS), json.dumps(WIP), now()))

conn.commit()
print("   Board configs created")

# ─── 17. AUTOMATION RULES ────────────────────────────────────────────────────
print("17. Creating automation rules...")
cur.execute("DELETE FROM automation_rules WHERE org_id=%s", (ORG,))
AUTOMATIONS = [
    ("DPAI", "Auto-assign blocked tickets to lead",
     "status_change", "status_is", {"status": "Blocked"},
     "assign_to", {"user_id": USERS["Abhishek Jain"]}, "Abhishek Jain"),
    ("NOVA", "Label high-priority bugs as urgent",
     "ticket_created", "priority_is", {"priority": "Highest"},
     "add_label", {"label": "urgent"}, "Anoop Rai"),
    ("AURA", "Post comment on ticket completion",
     "status_change", "status_is", {"status": "Done"},
     "post_comment", {"comment_body": "✅ Ticket completed and verified."}, "Seva Srinivasan"),
    ("PULSE", "Create QA subtask when ticket goes to In Review",
     "status_change", "status_is", {"status": "In Review"},
     "create_subtask", {"subtask_summary": "QA verification"}, "Anoop Rai"),
]
for pod, name, trigger, cond_type, cond_cfg, action_type, action_cfg, created_by_name in AUTOMATIONS:
    cur.execute("""
        INSERT INTO automation_rules (id, org_id, pod, name, trigger_type, trigger_config,
                                       condition_type, condition_config,
                                       action_type, action_config, is_active, run_count, created_by, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,0,%s,%s)
    """, (uid(), ORG, pod, name, trigger, json.dumps({}),
          cond_type, json.dumps(cond_cfg),
          action_type, json.dumps(action_cfg),
          USERS.get(created_by_name), now()))

conn.commit()
print(f"   Created {len(AUTOMATIONS)} automation rules")

# ─── 18. NOTIFICATIONS ───────────────────────────────────────────────────────
print("18. Creating notifications...")
user_ids = [v for k, v in USERS.items() if k != "Admin"]
NOTIF_TEMPLATES = [
    ("ticket_assigned",  "Ticket assigned to you",          "DPAI-5 has been assigned to you",                "/tickets?key=DPAI-5"),
    ("sprint_started",   "Sprint started",                   "DPAI — Sprint 3 has started. 14 tickets in.",    "/spaces/DPAI"),
    ("ticket_done",      "Ticket completed",                "NOVA-8 marked as Done",                          "/tickets?key=NOVA-8"),
    ("blocked_ticket",   "Ticket is blocked",               "AURA-15 is now blocked. Action needed.",         "/tickets?key=AURA-15"),
    ("burn_rate_alert",  "Budget warning: FinanceGroup",    "FinanceGroup has used 92.5% of monthly budget",  "/settings"),
    ("ticket_in_review", "PR ready for review",             "PULSE-6 is now In Review. Your input needed.",   "/tickets?key=PULSE-6"),
    ("mention",          "You were mentioned",              "@anand mentioned you in NOVA-4 comment",         "/tickets?key=NOVA-4"),
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

cur.close()
conn.close()
print()
print("=== Fix seed complete! ===")
