"""
seed_comprehensive.py — Fill all missing data:
1. Fix releases (link tickets via fix_version)
2. Add pod-specific decisions per pod
3. Add pod-specific processes per pod
4. Add rich wiki pages
5. Add manual_entries (timesheet) for all users — 3 months back
6. Add recent standup data
7. Link tickets to goal key_results
"""

import psycopg2, json, uuid, random
from datetime import date, timedelta, datetime

DB_URL = "postgresql://anandverma@localhost:5432/timesheet-tracker-db"
ORG    = "91da7ceb-c12d-4189-97aa-c4d2831b2e28"

def uid():   return str(uuid.uuid4())
def now():   return datetime.utcnow()
def today(): return date.today()

conn = psycopg2.connect(DB_URL)
cur  = conn.cursor()

# ── Lookup all users ──────────────────────────────────────────────────────────
cur.execute("SELECT id, name, email, pod FROM users WHERE org_id=%s", (ORG,))
ALL_USERS = cur.fetchall()   # [(id, name, email, pod), ...]

USERS_BY_POD = {}
for uid_, name, email, pod in ALL_USERS:
    USERS_BY_POD.setdefault(pod or "admin", []).append((uid_, name, email))

# ── Lookup wiki spaces ─────────────────────────────────────────────────────────
cur.execute("SELECT id, slug FROM wiki_spaces WHERE org_id=%s", (ORG,))
WIKI_SPACES = {slug: sid for sid, slug in cur.fetchall()}

# ────────────────────────────────────────────────────────────────────────────────
# 1. FIX RELEASES — set fix_version on tickets
# ────────────────────────────────────────────────────────────────────────────────
print("=== 1. Linking tickets to releases via fix_version ===")

RELEASE_TICKET_MAP = {
    # DPAI releases
    "DPAI": {
        "v1.0.0": ["DPAI-1","DPAI-2","DPAI-3","DPAI-5","DPAI-7"],
        "v1.2.0": ["DPAI-6","DPAI-8","DPAI-9","DPAI-10","DPAI-11","DPAI-12"],
        "v1.3.0": ["DPAI-13","DPAI-14","DPAI-15","DPAI-16","DPAI-17"],
        "v1.4.0": ["DPAI-18","DPAI-19","DPAI-20","DPAI-21","DPAI-22"],
    },
    # NOVA releases
    "NOVA": {
        "v2.1.0": ["NOVA-1","NOVA-2","NOVA-3","NOVA-4","NOVA-5","NOVA-6"],
        "v2.2.0": ["NOVA-7","NOVA-8","NOVA-9","NOVA-10","NOVA-11","NOVA-12","NOVA-13"],
        "v2.3.0": ["NOVA-14","NOVA-15","NOVA-16","NOVA-17","NOVA-18","NOVA-19","NOVA-20"],
    },
    # AURA releases
    "AURA": {
        "v3.0.0": ["AURA-1","AURA-2","AURA-3","AURA-4","AURA-5","AURA-6","AURA-7","AURA-8"],
        "v3.1.0": ["AURA-9","AURA-10","AURA-11","AURA-12","AURA-13","AURA-14","AURA-15","AURA-16","AURA-17","AURA-18","AURA-19","AURA-20"],
    },
    # PULSE releases
    "PULSE": {
        "v1.0.0": ["PULSE-1","PULSE-2","PULSE-3","PULSE-4","PULSE-5","PULSE-6"],
        "v1.1.0": ["PULSE-7","PULSE-8","PULSE-9","PULSE-10","PULSE-11","PULSE-12","PULSE-13"],
        "v1.2.0": ["PULSE-14","PULSE-15","PULSE-16","PULSE-17","PULSE-18","PULSE-19","PULSE-20"],
    },
}

for pod, versions in RELEASE_TICKET_MAP.items():
    for version, keys in versions.items():
        for key in keys:
            cur.execute("""
                UPDATE jira_tickets SET fix_version=%s
                WHERE jira_key=%s AND org_id=%s AND is_deleted=false
            """, (version, key, ORG))
        print(f"  {pod} {version}: linked {cur.rowcount}/{len(keys)} tickets")

conn.commit()
print("  ✓ Releases linked\n")


# ────────────────────────────────────────────────────────────────────────────────
# 2. POD-SPECIFIC DECISIONS
# ────────────────────────────────────────────────────────────────────────────────
print("=== 2. Adding pod-specific decisions ===")

# Get current max number
cur.execute("SELECT COALESCE(MAX(number),0) FROM decisions WHERE org_id=%s", (ORG,))
num = cur.fetchone()[0]

POD_DECISIONS = {
    "DPAI": [
        {
            "title": "Use React Query for all server-state management in DPAI",
            "status": "accepted",
            "context": "DPAI dashboard has complex data fetching with caching, background refresh, and optimistic updates. We need a consistent pattern.",
            "decision": "Use TanStack React Query v5 for all server-state. No Redux for server data.",
            "rationale": "React Query provides caching, refetching, and optimistic updates out of the box. Reduces boilerplate by ~60%.",
            "alternatives": ["Redux Toolkit Query", "SWR", "Zustand with manual fetching"],
            "consequences": "All new API calls go through useQuery/useMutation. Team needs familiarity with React Query concepts.",
            "tags": ["frontend", "architecture", "state-management"],
            "linked_tickets": ["DPAI-16", "DPAI-3"],
        },
        {
            "title": "Implement server-side pagination for ticket lists > 100 items",
            "status": "accepted",
            "context": "Dashboard ticket lists were loading all records causing slow renders and high memory usage on large datasets.",
            "decision": "All list endpoints accept limit/offset. Frontend uses infinite scroll with useInfiniteQuery.",
            "rationale": "DPAI-6 was directly caused by loading 2000+ tickets at once. Server pagination reduces p95 load time from 4.2s to 0.6s.",
            "alternatives": ["Virtual scrolling on client", "GraphQL pagination"],
            "consequences": "All list APIs must support limit/offset. Existing endpoints need migration.",
            "tags": ["performance", "api", "backend"],
            "linked_tickets": ["DPAI-6", "DPAI-8"],
        },
        {
            "title": "Feature flags via environment variables for DPAI experimental features",
            "status": "proposed",
            "context": "DPAI is rolling out AI-driven recommendations. Need to control rollout without code deploys.",
            "decision": "Use VITE_ prefixed env vars + backend FEATURE_* vars. No external service for now.",
            "rationale": "External feature flag services (LaunchDarkly, Split) add cost and latency. Env var approach is sufficient for current team size.",
            "alternatives": ["LaunchDarkly", "Unleash", "Database-backed flags"],
            "consequences": "Feature flags require server restart to change. Acceptable trade-off at current stage.",
            "tags": ["devops", "deployment", "ai"],
            "linked_tickets": ["DPAI-4"],
        },
    ],
    "NOVA": [
        {
            "title": "Nova AI uses streaming responses via SSE for long-running queries",
            "status": "accepted",
            "context": "Nova AI analysis queries can take 5-15 seconds. Users were seeing blank screens and abandoning.",
            "decision": "All Nova AI endpoints stream via Server-Sent Events. Frontend shows progressive rendering.",
            "rationale": "SSE is simpler than WebSockets for unidirectional streaming. Reduces perceived latency from 12s to first-token at <0.5s.",
            "alternatives": ["WebSockets", "Polling", "Long-polling"],
            "consequences": "Backend handlers must be async generators. Some reverse proxies need timeout config.",
            "tags": ["ai", "performance", "ux"],
            "linked_tickets": ["NOVA-1", "NOVA-5"],
        },
        {
            "title": "Separate embedding generation from query time using background jobs",
            "status": "accepted",
            "context": "pgvector similarity search was timing out when new tickets hadn't been embedded yet.",
            "decision": "On ticket create/update, enqueue an embedding job. Queries only read pre-computed embeddings.",
            "rationale": "Decoupling write path from AI pipeline. Ticket creation stays <100ms. Embeddings available within 30s.",
            "alternatives": ["Synchronous embedding on save", "Pre-compute nightly batch"],
            "consequences": "New tickets appear in semantic search with ~30s delay. Acceptable.",
            "tags": ["ai", "backend", "embeddings"],
            "linked_tickets": ["NOVA-3", "NOVA-7"],
        },
        {
            "title": "Nova citation system links AI answers to source tickets and wiki pages",
            "status": "accepted",
            "context": "Users couldn't trust Nova answers without knowing the source. Hallucination risk.",
            "decision": "Every Nova answer includes citation objects with source type, key, and quote snippet.",
            "rationale": "Increases trust and allows users to verify AI reasoning. Reduces hallucination reports by ~70% in testing.",
            "alternatives": ["Simple source links", "No citations", "Confidence scores only"],
            "consequences": "Response format is more complex. Frontend must handle citation rendering.",
            "tags": ["ai", "ux", "trust"],
            "linked_tickets": ["NOVA-10", "NOVA-13"],
        },
    ],
    "AURA": [
        {
            "title": "AURA payment module uses idempotency keys for all mutations",
            "status": "accepted",
            "context": "Retry logic in AURA payment flows was causing duplicate charges in 0.3% of cases.",
            "decision": "All payment API endpoints require Idempotency-Key header. Responses cached for 24h.",
            "rationale": "Industry standard for payment APIs. Eliminates duplicate charge risk entirely.",
            "alternatives": ["Client-side deduplication", "Short TTL response cache"],
            "consequences": "Clients must generate and track idempotency keys. Additional DB storage for cached responses.",
            "tags": ["payments", "reliability", "backend"],
            "linked_tickets": ["AURA-1", "AURA-3"],
        },
        {
            "title": "PCI-DSS compliance: no PAN data stored in application DB",
            "status": "accepted",
            "context": "AURA needs PCI-DSS Level 1 compliance for enterprise clients. Raw card data storage is prohibited.",
            "decision": "All card data tokenized via Stripe/Adyen. Only tokens stored in our DB.",
            "rationale": "Mandatory for compliance. Reduces PCI scope to SAQ A (simplest level).",
            "alternatives": ["Build own vault", "Use HSM", "Store encrypted PAN"],
            "consequences": "Vendor lock-in on tokenization provider. Acceptable trade-off for compliance.",
            "tags": ["compliance", "security", "payments"],
            "linked_tickets": ["AURA-5", "AURA-13"],
        },
        {
            "title": "AURA uses event sourcing for audit trail on all financial transactions",
            "status": "accepted",
            "context": "Financial audits require immutable history of all state changes. Standard CRUD overwrites history.",
            "decision": "Financial transaction model is append-only event log. Read models rebuilt from events.",
            "rationale": "Full audit trail required by regulators. Event sourcing provides this naturally.",
            "alternatives": ["Audit log table", "Change data capture", "Soft deletes only"],
            "consequences": "More complex read path. CQRS pattern required for performance.",
            "tags": ["compliance", "architecture", "payments"],
            "linked_tickets": ["AURA-8", "AURA-16"],
        },
    ],
    "PULSE": [
        {
            "title": "PULSE client portal uses subdomain-per-tenant routing",
            "status": "accepted",
            "context": "Enterprise clients want white-labelled portals. Shared URL feels generic.",
            "decision": "Each client gets {client}.pulse.3sc.ai subdomain. Wildcard SSL + nginx routing.",
            "rationale": "White-labelling is a key enterprise differentiator. Subdomain routing is proven at scale.",
            "alternatives": ["Path-based routing /client/xyz", "Separate deployments per client"],
            "consequences": "Wildcard certificate management. DNS provisioning automation needed.",
            "tags": ["infrastructure", "enterprise", "routing"],
            "linked_tickets": ["PULSE-1", "PULSE-5"],
        },
        {
            "title": "PULSE reports use async PDF generation with email delivery",
            "status": "accepted",
            "context": "Large client reports (50+ pages) were timing out at 30s gateway limit.",
            "decision": "Report generation is async job. User gets email with download link when ready.",
            "rationale": "Eliminates timeout issue entirely. Better UX — user doesn't wait watching spinner.",
            "alternatives": ["Increase gateway timeout", "Paginated reports only", "CSV instead of PDF"],
            "consequences": "Users need to check email. Requires async job infrastructure and S3 storage.",
            "tags": ["reports", "async", "ux"],
            "linked_tickets": ["PULSE-6", "PULSE-11"],
        },
        {
            "title": "PULSE uses role-based data scoping — clients see only their data",
            "status": "accepted",
            "context": "PULSE serves multiple clients. Data isolation is critical for enterprise trust.",
            "decision": "Every query in PULSE routes includes client_id from JWT claim. RLS via application code.",
            "rationale": "Data isolation enforced at application layer with explicit client_id filtering on every query.",
            "alternatives": ["PostgreSQL RLS", "Separate schemas per client", "Separate databases"],
            "consequences": "Developers must remember to add client filter on every query. Code reviews must check this.",
            "tags": ["security", "multi-tenant", "compliance"],
            "linked_tickets": ["PULSE-3", "PULSE-7"],
        },
    ],
}

for pod, decisions in POD_DECISIONS.items():
    for d in decisions:
        num += 1
        cur.execute("""
            INSERT INTO decisions (id, org_id, number, title, status, owner, date,
                context, decision, rationale, alternatives, consequences,
                linked_tickets, tags, space_id, org_level, is_deleted, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s)
            ON CONFLICT (id) DO NOTHING
        """, (
            uid(), ORG, num, d["title"], d["status"],
            random.choice(USERS_BY_POD.get(pod, USERS_BY_POD.get("DPAI",[("","","")]))[0:1])[1] if USERS_BY_POD.get(pod) else "Admin",
            (today() - timedelta(days=random.randint(7,90))).isoformat(),
            d["context"], d["decision"], d["rationale"],
            d["alternatives"], d["consequences"],
            d["linked_tickets"], d["tags"],
            pod,   # space_id = pod name
            False, # not org-level
            now(), now()
        ))
    print(f"  {pod}: +{len(decisions)} decisions")

conn.commit()
print("  ✓ Decisions added\n")


# ────────────────────────────────────────────────────────────────────────────────
# 3. POD-SPECIFIC PROCESSES
# ────────────────────────────────────────────────────────────────────────────────
print("=== 3. Adding pod-specific processes ===")

def steps(*items):
    return json.dumps([
        {"id": uid(), "order": i+1, "title": t, "description": desc,
         "owner": None, "estimatedTime": est, "required": True}
        for i, (t, desc, est) in enumerate(items)
    ])

POD_PROCESSES = {
    "DPAI": [
        {
            "title": "DPAI Bug Triage Process",
            "category": "sop",
            "status": "active",
            "description": "Standard process for triaging bugs reported in DPAI dashboard. Ensures critical bugs are addressed within 24h SLA.",
            "tags": ["bugs", "triage", "quality"],
            "compliance_required": False,
            "run_count": 12,
            "steps": steps(
                ("Reproduce the bug", "Verify the bug exists in the latest build on staging environment.", "15 mins"),
                ("Classify severity", "Assign severity: Critical (data loss/crash), High (feature broken), Medium (workaround exists), Low (cosmetic).", "10 mins"),
                ("Create/update ticket", "Ensure ticket has: steps to reproduce, expected vs actual, environment, screenshots.", "20 mins"),
                ("Assign and prioritize", "Assign to appropriate engineer. Critical → current sprint. High → next sprint.", "10 mins"),
                ("Notify stakeholders", "For Critical/High bugs, post in #dpai-alerts with ETA.", "5 mins"),
            ),
        },
        {
            "title": "DPAI Feature Release Checklist",
            "category": "runbook",
            "status": "active",
            "description": "Pre-release checklist for all DPAI feature deployments to production.",
            "tags": ["release", "deployment", "checklist"],
            "compliance_required": True,
            "run_count": 4,
            "steps": steps(
                ("Code review approval", "All PRs must have 2 approvals from team members.", "varies"),
                ("Run full test suite", "Execute npm test and ensure 100% of existing tests pass.", "30 mins"),
                ("Update API documentation", "Ensure Swagger docs are updated for any new/changed endpoints.", "20 mins"),
                ("Deploy to staging", "Deploy feature branch to staging.dpai.3sc.ai and run smoke tests.", "15 mins"),
                ("Product sign-off", "Product owner validates feature against acceptance criteria.", "30 mins"),
                ("Production deployment", "Deploy via CI/CD pipeline. Monitor error rates for 30 mins post-deploy.", "45 mins"),
            ),
        },
        {
            "title": "DPAI On-Call Incident Response",
            "category": "runbook",
            "status": "active",
            "description": "Response playbook for on-call engineers when DPAI alerts fire.",
            "tags": ["oncall", "incident", "sre"],
            "compliance_required": True,
            "run_count": 7,
            "steps": steps(
                ("Acknowledge the alert", "Acknowledge PagerDuty alert within 5 minutes.", "5 mins"),
                ("Assess impact", "Determine number of affected users and business impact.", "10 mins"),
                ("Start incident channel", "Create #incident-YYYY-MM-DD channel, post initial summary.", "5 mins"),
                ("Investigate root cause", "Check logs in Datadog, recent deployments, upstream dependencies.", "varies"),
                ("Implement fix or rollback", "If root cause identified: fix and deploy. If unclear: rollback last deployment.", "30 mins"),
                ("Write incident report", "Document timeline, root cause, impact, and preventive actions within 48h.", "60 mins"),
            ),
        },
    ],
    "NOVA": [
        {
            "title": "Nova AI Model Evaluation Process",
            "category": "sop",
            "status": "active",
            "description": "Process for evaluating new AI models or prompt changes before deploying to Nova production.",
            "tags": ["ai", "quality", "evaluation"],
            "compliance_required": True,
            "run_count": 5,
            "steps": steps(
                ("Define evaluation criteria", "Set accuracy thresholds: >85% on golden test set, <2s p99 latency.", "30 mins"),
                ("Run golden dataset evaluation", "Execute eval_runner.py against 200-question golden set.", "60 mins"),
                ("Compare with baseline", "New model must match or exceed baseline on all metrics.", "20 mins"),
                ("A/B test with 10% traffic", "Route 10% of Nova queries to new model. Monitor for 48h.", "48 hrs"),
                ("Review user feedback", "Check thumbs-up/down ratings. Accept if positive rate > 80%.", "30 mins"),
                ("Full rollout", "Promote new model to 100% traffic. Archive old model.", "30 mins"),
            ),
        },
        {
            "title": "Knowledge Gap Detection SOP",
            "category": "sop",
            "status": "active",
            "description": "Weekly process to identify and prioritize wiki gaps detected by Nova AI.",
            "tags": ["knowledge", "wiki", "ai"],
            "compliance_required": False,
            "run_count": 8,
            "steps": steps(
                ("Run gap detection", "Execute nova detect-gaps CLI or trigger from admin panel.", "10 mins"),
                ("Review top 10 gaps", "Review gaps with wiki_coverage < 0.3 and ticket_count > 5.", "30 mins"),
                ("Assign wiki articles", "Assign each high-priority gap to an SME. Create draft pages.", "20 mins"),
                ("Track completion", "Update gap status in the knowledge gaps dashboard weekly.", "10 mins"),
            ),
        },
    ],
    "AURA": [
        {
            "title": "AURA PCI Compliance Audit Preparation",
            "category": "compliance",
            "status": "active",
            "description": "Quarterly preparation process for PCI-DSS audit. Ensures all controls are documented and evidence is ready.",
            "tags": ["compliance", "pci", "audit", "security"],
            "compliance_required": True,
            "run_count": 2,
            "steps": steps(
                ("Update network diagram", "Confirm cardholder data environment (CDE) boundary diagram is current.", "60 mins"),
                ("Review access logs", "Pull 90-day access logs for all CDE systems. Look for anomalies.", "120 mins"),
                ("Verify vulnerability scan", "Confirm ASV scan completed within last 90 days. No critical findings.", "30 mins"),
                ("Review penetration test", "Confirm annual pen test report is current and findings remediated.", "60 mins"),
                ("Update policies", "Review and update all PCI policies. Get sign-off from CISO.", "120 mins"),
                ("Mock audit walkthrough", "Internal walkthrough with QSA questions. Fix any gaps found.", "180 mins"),
                ("Submit evidence package", "Compile all evidence and submit to QSA 2 weeks before audit.", "60 mins"),
            ),
        },
        {
            "title": "AURA Payment Incident Escalation",
            "category": "runbook",
            "status": "active",
            "description": "Escalation procedure when payment processing errors exceed 0.1% error rate.",
            "tags": ["payments", "incident", "escalation"],
            "compliance_required": True,
            "run_count": 3,
            "steps": steps(
                ("Detect threshold breach", "Automated alert fires when payment error rate > 0.1% in 5-min window.", "auto"),
                ("Notify payment team", "Page on-call payment engineer. Notify Head of Payments via Slack.", "2 mins"),
                ("Assess scope", "Check: processor status page, affected payment methods, client segments.", "10 mins"),
                ("Activate circuit breaker", "If processor issue: disable affected payment method, redirect to backup.", "5 mins"),
                ("Client communications", "Send templated comms to affected clients via CSM team.", "15 mins"),
                ("Resolve and monitor", "Fix root cause. Monitor until error rate returns to <0.01% for 30 mins.", "varies"),
            ),
        },
    ],
    "PULSE": [
        {
            "title": "PULSE New Client Onboarding Workflow",
            "category": "workflow",
            "status": "active",
            "description": "End-to-end process for onboarding a new enterprise client to PULSE platform.",
            "tags": ["onboarding", "client", "enterprise"],
            "compliance_required": False,
            "run_count": 6,
            "steps": steps(
                ("Sign MSA and SOW", "Ensure Master Service Agreement and Statement of Work are fully executed.", "varies"),
                ("Provision tenant", "Run: ./scripts/provision_client.sh {client_slug}. Creates DB, subdomain, admin user.", "30 mins"),
                ("Configure branding", "Set client logo, colors, domain in admin panel. Verify subdomain resolves.", "60 mins"),
                ("Data migration", "If migrating from legacy system: run ETL pipeline. Verify row counts match.", "4 hrs"),
                ("User setup", "Create accounts for all client users. Send welcome emails with SSO config.", "60 mins"),
                ("Training session", "Conduct 90-min training session with client team. Record for async access.", "90 mins"),
                ("Hypercare week", "Daily check-in calls for first 7 days. Monitor error rates closely.", "7 days"),
            ),
        },
        {
            "title": "PULSE Monthly Client Report Generation",
            "category": "template",
            "status": "active",
            "description": "Template for generating and delivering monthly performance reports to PULSE clients.",
            "tags": ["reports", "client", "monthly"],
            "compliance_required": False,
            "run_count": 15,
            "steps": steps(
                ("Pull report data", "Run generate_report.py --client={client} --month={YYYY-MM}. Takes ~5 mins.", "10 mins"),
                ("Review metrics", "Verify KPIs match client's contractual SLAs. Flag any breaches.", "30 mins"),
                ("Add commentary", "Write executive summary: highlights, concerns, recommendations.", "45 mins"),
                ("Get internal approval", "Slack the draft to account lead for approval before sending.", "24 hrs"),
                ("Deliver to client", "Send via secure portal. CC CSM and account lead.", "10 mins"),
            ),
        },
    ],
}

for pod, proc_list in POD_PROCESSES.items():
    for p in proc_list:
        cur.execute("""
            INSERT INTO processes (id, org_id, title, category, status, owner, last_updated,
                description, steps, tags, compliance_required, avg_completion_time,
                run_count, space_id, org_level, is_deleted, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s,%s)
            ON CONFLICT (id) DO NOTHING
        """, (
            uid(), ORG, p["title"], p["category"], p["status"],
            random.choice(USERS_BY_POD.get(pod, [("","Admin","")])[0:1])[1],
            (today() - timedelta(days=random.randint(1,30))).isoformat(),
            p["description"], p["steps"], p["tags"],
            p["compliance_required"], "varies", p["run_count"],
            pod, False, now(), now()
        ))
    print(f"  {pod}: +{len(proc_list)} processes")

conn.commit()
print("  ✓ Processes added\n")


# ────────────────────────────────────────────────────────────────────────────────
# 4. RICH WIKI PAGES
# ────────────────────────────────────────────────────────────────────────────────
print("=== 4. Adding rich wiki pages ===")

ENG_HUB_ID   = WIKI_SPACES.get("eng-hub")
PRODUCT_ID   = WIKI_SPACES.get("product")
ONBOARDING_ID= WIKI_SPACES.get("onboarding")
CLIENTS_ID   = WIKI_SPACES.get("clients")
TRACKLY_ID   = WIKI_SPACES.get("trackly")

ADMIN_ID = next((uid_ for uid_, n, e, p in ALL_USERS if "admin" in e.lower()), ALL_USERS[0][0])
ANAND_ID = next((uid_ for uid_, n, e, p in ALL_USERS if "anand" in e.lower()), ALL_USERS[0][0])

new_pages = []

if ENG_HUB_ID:
    new_pages += [
        (uid(), ENG_HUB_ID, None, "Local Development Setup Guide",
         """# Local Development Setup Guide

## Prerequisites
- Node.js 20+ (use nvm)
- Python 3.11+
- PostgreSQL 15 with pgvector extension
- Docker (optional, for services)

## Frontend Setup
```bash
cd trackly-frontend
npm install
cp .env.example .env.local
npm run dev
```
The frontend runs at `http://localhost:3000`.

## Backend Setup
```bash
cd trackly-backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

## Running Tests
```bash
# Frontend
npm run test

# Backend
pytest tests/ -v
```

## Troubleshooting
- **pgvector not found**: Install with `CREATE EXTENSION vector;` in psql
- **Port 8000 in use**: Kill with `lsof -ti:8000 | xargs kill`
- **DB connection refused**: Check PostgreSQL is running: `brew services start postgresql@15`
"""),
        (uid(), ENG_HUB_ID, None, "Code Review Guidelines",
         """# Code Review Guidelines

## Philosophy
Code review is about **quality and knowledge sharing**, not gatekeeping.

## What to Look For
1. **Correctness** — Does the code do what it claims? Edge cases handled?
2. **Security** — No hardcoded secrets, no SQL injection, no XSS
3. **Performance** — No N+1 queries, no blocking I/O in async context
4. **Readability** — Clear variable names, no unnecessary complexity
5. **Tests** — New logic has test coverage

## SLA
- PRs < 200 lines: review within **4 hours**
- PRs > 200 lines: review within **1 business day**
- Block only for: bugs, security issues, or missing tests

## How to Give Feedback
- Use conventional comment types: `nit:`, `suggestion:`, `blocker:`
- Be specific — point to line, not file
- Offer alternative if you block something

## PR Description Template
```
## What
Brief description of the change.

## Why
The motivation (link to ticket).

## Testing
How you tested this. Screenshots if UI change.
```
"""),
        (uid(), ENG_HUB_ID, None, "Database Migration Runbook",
         """# Database Migration Runbook

## Adding a Column (Safe)
```sql
-- Always add with DEFAULT to avoid table lock on large tables
ALTER TABLE jira_tickets ADD COLUMN IF NOT EXISTS risk_score FLOAT DEFAULT 0;
```

## Adding an Index (Safe — use CONCURRENTLY)
```sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_tickets_status
ON jira_tickets(org_id, status);
```

## Dropping a Column (Careful!)
1. Deploy code that ignores the column
2. Wait 1 deploy cycle
3. Then drop: `ALTER TABLE x DROP COLUMN y;`

## Running Migrations
```bash
# Generate
alembic revision --autogenerate -m "add risk_score to tickets"

# Review the generated file BEFORE applying
cat alembic/versions/latest.py

# Apply
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Never Do This on Production
- `DROP TABLE` without backup
- `ALTER TYPE` on enum (drop+recreate instead)
- Long transactions holding locks during peak hours
"""),
        (uid(), ENG_HUB_ID, None, "API Design Standards",
         """# API Design Standards

## URL Structure
```
GET    /api/{resource}           # List
POST   /api/{resource}           # Create
GET    /api/{resource}/{id}      # Get one
PUT    /api/{resource}/{id}      # Full update
PATCH  /api/{resource}/{id}      # Partial update
DELETE /api/{resource}/{id}      # Delete
```

## Response Format
All responses wrap data:
```json
{
  "data": [...],
  "total": 100,
  "limit": 20,
  "offset": 0
}
```

## Error Format
```json
{
  "detail": "Human-readable error message",
  "code": "ERROR_CODE",
  "field": "field_name"
}
```

## Pagination
- Always paginate lists: `?limit=20&offset=0`
- Max limit: 100
- Return `total` count in response

## Auth
All endpoints require `Authorization: Bearer {token}` header.
Public endpoints explicitly documented.

## Versioning
No URL versioning yet. Breaking changes go through deprecation period.
"""),
    ]

if PRODUCT_ID:
    new_pages += [
        (uid(), PRODUCT_ID, None, "Product Roadmap Q2 2026",
         """# Product Roadmap Q2 2026

## Theme: "AI-Powered Sprint Intelligence"

### Must Ship (P0)
| Feature | Owner | ETA | Status |
|---------|-------|-----|--------|
| Nova AI v2 — multi-doc RAG | NOVA | May 15 | 🟡 In Progress |
| Sprint Risk Heatmap | DPAI | May 30 | 🟡 In Progress |
| AURA PCI-DSS Level 1 cert | AURA | Jun 30 | 🔴 At Risk |
| PULSE client portal GA | PULSE | Jun 15 | 🟢 On Track |

### Should Ship (P1)
- Automated standup generation from ticket activity
- Knowledge gap auto-detection
- Sprint what-if scenario modeler

### Won't Ship This Quarter
- Mobile app (moved to Q3)
- SSO with SAML (moved to Q3 — blocked on security review)

## Success Metrics
- Sprint delivery rate > 90% across all pods
- Nova answer accuracy > 85% on eval set
- PULSE client NPS > 45
"""),
        (uid(), PRODUCT_ID, None, "Design System — Component Library",
         """# Design System

## Color Tokens
```css
--accent:     #4F7EFF;  /* Primary blue */
--amber:      #FBBF24;  /* Warning */
--red:        #F87171;  /* Error/danger */
--green:      #34D399;  /* Success */
--purple:     #A78BFA;  /* Info/AI */
--surface-1:  #0F1117;  /* Page bg */
--surface-2:  #161B27;  /* Card bg */
--border-1:   #1E2535;  /* Borders */
--text-1:     #F1F5F9;  /* Primary text */
--text-2:     #94A3B8;  /* Secondary text */
--text-3:     #475569;  /* Muted text */
```

## Component Conventions
- All interactive elements have `:hover` and `:focus-visible` states
- Use `motion.div` from framer-motion for all animations
- Loading states use skeleton shimmer, not spinners
- Errors show toast notifications (react-hot-toast)

## Typography Scale
```css
--font-xl:   1.5rem;   /* Page titles */
--font-lg:   1.125rem; /* Section headers */
--font-md:   0.875rem; /* Body */
--font-sm:   0.75rem;  /* Labels */
--font-xs:   0.6875rem;/* Badges */
```
"""),
    ]

if ONBOARDING_ID:
    new_pages += [
        (uid(), ONBOARDING_ID, None, "Week 1 — Getting Started",
         """# Week 1 — Getting Started

Welcome to the team! Here's what to do in your first week.

## Day 1
- [ ] Complete HR onboarding (Workday)
- [ ] Set up laptop using IT setup guide
- [ ] Join Slack — ask your buddy for channel list
- [ ] Set up local dev environment (see Engineering Hub)
- [ ] Meet your team lead for 1:1

## Day 2–3
- [ ] Read the product overview (Product wiki space)
- [ ] Walk through the codebase with your buddy
- [ ] Pick up your first starter ticket (tagged `good-first-issue`)
- [ ] Shadow a standup call

## Day 4–5
- [ ] Complete your first PR (even if small)
- [ ] Meet with the engineering manager
- [ ] Review the team working agreements

## Tools Access Checklist
- [ ] GitHub (org: 3sc-ai)
- [ ] Figma (product design)
- [ ] Datadog (monitoring)
- [ ] PagerDuty (on-call)
- [ ] AWS Console (read-only initially)
"""),
        (uid(), ONBOARDING_ID, None, "Team Working Agreements",
         """# Team Working Agreements

## Communication
- **Async-first**: Default to Slack messages, not meetings
- **Response SLA**: Reply to Slack within 4 hours during working hours
- **Status updates**: Update ticket status daily — never leave stale for >2 days
- **No passive-aggressive messages**: Address concerns directly

## Meetings
- **Daily standup**: 10:00 AM IST, 15 minutes max
- **Sprint planning**: First Monday of sprint, 2 hours
- **Retro**: Last Friday of sprint, 1 hour
- All meetings have an agenda sent 24h in advance

## Code
- **Branch naming**: `feat/TICKET-123-short-description`
- **Commit messages**: Start with verb: "Add", "Fix", "Update", "Remove"
- **PR size**: < 400 lines preferred. Large PRs split into logical chunks
- **Tests required**: No PR merges without tests for new logic

## Work Hours
- Core hours: 11 AM – 5 PM IST (overlapping with all time zones)
- Flexible outside core hours
- Mark OOO in Slack status and calendar
"""),
    ]

for row in new_pages:
    page_id, space_id, parent_id, title, content = row
    cur.execute("""
        INSERT INTO wiki_pages (id, space_id, parent_id, org_id, title,
            content_md, content_html, version, author_id, is_deleted, created_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,1,%s,false,%s,%s)
        ON CONFLICT (id) DO NOTHING
    """, (page_id, space_id, parent_id, ORG, title, content,
          f"<p>{title}</p>", ANAND_ID, now(), now()))

conn.commit()
print(f"  ✓ Added {len(new_pages)} wiki pages\n")


# ────────────────────────────────────────────────────────────────────────────────
# 5. MANUAL ENTRIES (TIMESHEET) — last 90 days for all users
# ────────────────────────────────────────────────────────────────────────────────
print("=== 5. Adding timesheet (manual_entries) for all users ===")

CLIENTS_BY_POD = {
    "DPAI":  ["Accenture", "TechCorp"],
    "NOVA":  ["FinanceGroup", "TechCorp"],
    "AURA":  ["RetailCo", "FinanceGroup"],
    "PULSE": ["HealthFirst", "Accenture"],
    "admin": ["Accenture"],
}

ENTRY_TYPES = ["Feature", "Bugs", "Review", "Meeting", "Planning", "Other"]

ACTIVITIES_BY_POD = {
    "DPAI": [
        ("Dashboard feature development", "Feature"),
        ("Bug fixing and QA", "Bugs"),
        ("Code review", "Review"),
        ("Sprint planning", "Planning"),
        ("Architecture design", "Feature"),
        ("API integration", "Feature"),
        ("Performance optimization", "Feature"),
        ("Unit test writing", "Feature"),
        ("Design review session", "Review"),
        ("Team standup and sync", "Meeting"),
    ],
    "NOVA": [
        ("AI model evaluation", "Feature"),
        ("RAG pipeline development", "Feature"),
        ("Embedding generation pipeline", "Feature"),
        ("Nova API development", "Feature"),
        ("Prompt engineering", "Feature"),
        ("Integration testing", "Review"),
        ("Documentation writing", "Other"),
        ("Client demo preparation", "Meeting"),
        ("Bug investigation — Nova", "Bugs"),
        ("Sprint planning", "Planning"),
    ],
    "AURA": [
        ("Payment module development", "Feature"),
        ("PCI compliance documentation", "Other"),
        ("Security audit work", "Review"),
        ("Payment gateway integration", "Feature"),
        ("Load testing", "Review"),
        ("Code review", "Review"),
        ("Infrastructure setup", "Feature"),
        ("Bug investigation", "Bugs"),
        ("Client requirements review", "Meeting"),
        ("Sprint planning", "Planning"),
    ],
    "PULSE": [
        ("Client portal development", "Feature"),
        ("Report generation pipeline", "Feature"),
        ("ETL development", "Feature"),
        ("Client onboarding support", "Other"),
        ("Dashboard customization", "Feature"),
        ("SLA monitoring", "Other"),
        ("Data migration", "Feature"),
        ("Client training session", "Meeting"),
        ("Bug fixing", "Bugs"),
        ("Sprint planning", "Planning"),
    ],
}

count = 0
START_DATE = today() - timedelta(days=90)

for uid_, name, email, pod in ALL_USERS:
    if not pod:  # skip admin
        continue

    activities   = ACTIVITIES_BY_POD.get(pod, ["General development"])
    clients      = CLIENTS_BY_POD.get(pod, ["Accenture"])
    # Add 3 entries per week for 12 weeks = ~36 entries per user
    cur_date = START_DATE
    while cur_date <= today():
        # Skip weekends
        if cur_date.weekday() >= 5:
            cur_date += timedelta(days=1)
            continue
        # ~3 working days out of 5 per week have entries (60% chance)
        if random.random() > 0.6:
            cur_date += timedelta(days=1)
            continue

        hours             = round(random.uniform(4.0, 8.0) * 2) / 2  # 4.0–8.0 in 0.5 steps
        activity, etype   = random.choice(activities)
        client            = random.choice(clients)

        cur.execute("""
            INSERT INTO manual_entries
                (id, user_id, org_id, entry_date, activity, hours,
                 pod, client, entry_type, status, ai_parsed, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'approved',false,%s,%s)
        """, (uid(), uid_, ORG, cur_date, activity, hours, pod, client, etype, now(), now()))
        count += 1
        cur_date += timedelta(days=1)

conn.commit()
print(f"  ✓ Added {count} timesheet entries across {len([u for u in ALL_USERS if u[3]])} users\n")


# ────────────────────────────────────────────────────────────────────────────────
# 6. STANDUP DATA — last 14 days (weekdays) for all users
# ────────────────────────────────────────────────────────────────────────────────
print("=== 6. Adding standup data ===")

STANDUP_TEMPLATES = {
    "DPAI": {
        "yesterday": [
            "Worked on {ticket} — {desc}. Completed initial implementation.",
            "Fixed bug in dashboard filter component. Reviewed 2 PRs from team.",
            "Sprint planning session. Refined backlog tickets for next sprint.",
            "Optimized SQL queries for analytics endpoint. Reduced p95 from 2.1s to 0.4s.",
            "Completed design review with Figma. Started implementation of drag-and-drop.",
        ],
        "today": [
            "Continue work on {ticket}. Write unit tests. PR by EOD.",
            "Investigate {ticket} — dashboard slow load. Check N+1 queries.",
            "Finish code review queue (3 PRs pending). Start story decomposition.",
            "Deploy hotfix for {ticket} to staging. Monitor and promote to prod.",
            "Pair programming with Akanksha on widget renderer fix.",
        ],
        "blockers": [
            "None", "None", "None",
            "Waiting for design specs on export feature from Figma.",
            "API rate limit issue with TechCorp sandbox environment.",
        ],
    },
    "NOVA": {
        "yesterday": [
            "Ran golden dataset eval on new Claude model. Accuracy: 87.3%.",
            "Implemented streaming SSE for Nova query endpoint. Tested locally.",
            "Fixed embedding mismatch bug — wrong tokenizer was used.",
            "Client demo prep for FinanceGroup. Built custom query examples.",
            "Reviewed and merged RAG pipeline PR. Updated docs.",
        ],
        "today": [
            "A/B test setup for new model — route 10% traffic. Monitor accuracy.",
            "Fix citation extraction — some quotes are being truncated.",
            "Knowledge gap detection run for this week. Assign wiki drafts.",
            "Latency optimization — cache frequent queries in Redis.",
            "Write eval harness for multi-document RAG.",
        ],
        "blockers": [
            "None", "None",
            "Need access to FinanceGroup's historical ticket data for fine-tuning.",
            "Claude API rate limits hitting during peak eval runs.",
        ],
    },
    "AURA": {
        "yesterday": [
            "PCI compliance documentation updated — network diagram revised.",
            "Implemented idempotency key validation for payment endpoints.",
            "Security pen test finding remediated — fixed CORS misconfiguration.",
            "Code review for payment gateway integration PR.",
            "Load tested payment endpoints at 1000 TPS. No issues.",
        ],
        "today": [
            "Continue PCI audit prep. Review access logs for Q1.",
            "Implement circuit breaker for Stripe API calls.",
            "Fix race condition in payment status webhook handler.",
            "Write runbook for payment processor failover.",
            "Sync with QSA on audit timeline and evidence package.",
        ],
        "blockers": [
            "None", "None",
            "Waiting for Stripe sandbox credentials from DevOps.",
            "PCI QSA hasn't confirmed audit dates yet.",
        ],
    },
    "PULSE": {
        "yesterday": [
            "Client onboarding for RetailCo — provisioned tenant, configured branding.",
            "Monthly report generation pipeline — fixed date range bug.",
            "Subdomain routing setup for HealthFirst.pulse.3sc.ai.",
            "ETL pipeline run for data migration. 98.7% success rate.",
            "Hypercare call with Accenture team — 5 issues logged and triaged.",
        ],
        "today": [
            "Training session with HealthFirst team (90 mins at 2pm IST).",
            "Investigate report timeout for large client — optimize PDF generation.",
            "Deploy client portal v1.1.0 to staging. Run smoke tests.",
            "Fix timezone bug in client reporting dashboard.",
            "Review SLA metrics for all clients. Flag any breaches.",
        ],
        "blockers": [
            "None", "None",
            "Waiting for HealthFirst to confirm user list for provisioning.",
            "PDF library license renewal pending — can't add new features.",
        ],
    },
}

TICKETS_BY_POD = {}
cur.execute("SELECT jira_key, summary, pod FROM jira_tickets WHERE org_id=%s AND is_deleted=false", (ORG,))
for key, summary, pod in cur.fetchall():
    TICKETS_BY_POD.setdefault(pod, []).append((key, summary[:50]))

count = 0
standup_date = today() - timedelta(days=14)
while standup_date <= today():
    if standup_date.weekday() >= 5:
        standup_date += timedelta(days=1)
        continue

    for uid_, name, email, pod in ALL_USERS:
        if not pod:
            continue
        # Check if standup already exists for this user+date
        cur.execute("SELECT 1 FROM standups WHERE user_id=%s AND date=%s", (uid_, standup_date))
        if cur.fetchone():
            standup_date_next = standup_date  # will advance below
            continue

        tmpl = STANDUP_TEMPLATES.get(pod, STANDUP_TEMPLATES["DPAI"])
        tickets = TICKETS_BY_POD.get(pod, [("TRKLY-1", "work item")])
        ticket  = random.choice(tickets)

        yesterday = random.choice(tmpl["yesterday"]).format(
            ticket=ticket[0], desc=ticket[1]
        )
        today_txt = random.choice(tmpl["today"]).format(
            ticket=random.choice(tickets)[0]
        )
        blockers  = random.choice(tmpl["blockers"])

        cur.execute("""
            INSERT INTO standups (id, user_id, org_id, date, yesterday, today, blockers, is_shared, generated_at)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, true, now())
            ON CONFLICT DO NOTHING
        """, (uid_, ORG, standup_date, yesterday, today_txt, blockers))
        count += 1

    standup_date += timedelta(days=1)

conn.commit()
print(f"  ✓ Added {count} standup entries\n")


# ────────────────────────────────────────────────────────────────────────────────
# 7. LINK TICKETS TO GOAL KEY RESULTS
# ────────────────────────────────────────────────────────────────────────────────
print("=== 7. Linking tickets to goals ===")

cur.execute("SELECT id, title, key_results FROM goals WHERE org_id=%s", (ORG,))
all_goals = cur.fetchall()

GOAL_TICKET_LINKS = {
    "Achieve 95% sprint delivery rate": ["DPAI-8","DPAI-10","NOVA-11","NOVA-15","AURA-12","PULSE-11"],
    "Ship EOS AI Agent v2": ["NOVA-1","NOVA-5","NOVA-10","NOVA-13","NOVA-16"],
    "Achieve PCI-DSS Level 1": ["AURA-1","AURA-3","AURA-5","AURA-13","AURA-16"],
    "Launch PULSE client portal": ["PULSE-1","PULSE-3","PULSE-5","PULSE-7","PULSE-16"],
    "Reduce bug rate by 40%": ["DPAI-2","DPAI-5","DPAI-6","NOVA-3","AURA-3","PULSE-4"],
    "Establish team health baseline": ["DPAI-15","NOVA-9","AURA-14","PULSE-15"],
}

for goal_id, title, key_results_json in all_goals:
    matched_tickets = []
    for pattern, tickets in GOAL_TICKET_LINKS.items():
        if pattern.lower() in title.lower():
            matched_tickets = tickets
            break

    if not matched_tickets:
        continue

    # Update key_results to include linked tickets
    krs = key_results_json or []
    if isinstance(krs, str):
        krs = json.loads(krs)

    for kr in krs:
        if not kr.get("linked_tickets"):
            kr["linked_tickets"] = matched_tickets[:3]
        elif len(kr["linked_tickets"]) < 2:
            kr["linked_tickets"] = matched_tickets[:3]

    cur.execute("UPDATE goals SET key_results=%s WHERE id=%s", (json.dumps(krs), goal_id))
    print(f"  Goal: {title[:50]!r} → {matched_tickets[:3]}")

conn.commit()
print("  ✓ Goals updated\n")


# ────────────────────────────────────────────────────────────────────────────────
# Final summary
# ────────────────────────────────────────────────────────────────────────────────
cur.execute("""
SELECT
    (SELECT count(*) FROM jira_tickets WHERE fix_version IS NOT NULL AND org_id=%s) as tickets_with_release,
    (SELECT count(*) FROM decisions WHERE org_id=%s AND space_id IS NOT NULL AND space_id != '') as pod_decisions,
    (SELECT count(*) FROM processes WHERE org_id=%s AND space_id IS NOT NULL AND space_id != '') as pod_processes,
    (SELECT count(*) FROM wiki_pages WHERE org_id=%s AND is_deleted=false) as wiki_pages,
    (SELECT count(*) FROM manual_entries WHERE org_id=%s) as timesheet_entries,
    (SELECT count(*) FROM standups WHERE org_id=%s) as standups
""", (ORG,)*6)
row = cur.fetchone()
print("=== Final DB State ===")
print(f"  Tickets with release:  {row[0]}")
print(f"  Pod-specific decisions: {row[1]}")
print(f"  Pod-specific processes: {row[2]}")
print(f"  Wiki pages:            {row[3]}")
print(f"  Timesheet entries:     {row[4]}")
print(f"  Standup entries:       {row[5]}")

conn.close()
print("\nDone! ✓")
