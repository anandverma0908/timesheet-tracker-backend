"""
seeds/seed_wiki.py — Insert 12 wiki pages across 4 spaces + generate embeddings.
Run via: python seeds/seed_all.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from app.core.database import SessionLocal
from app.models.wiki import WikiSpace, WikiPage
from app.models.base import gen_uuid

SPACES = [
    {"name": "Engineering",  "slug": "engineering",  "description": "Architecture decisions, runbooks, standards"},
    {"name": "DPAI",         "slug": "dpai",          "description": "DPAI project documentation"},
    {"name": "SNOP",         "slug": "snop",          "description": "SNOP project documentation"},
    {"name": "Processes",    "slug": "processes",     "description": "Team processes and on-call guides"},
]

PAGES = [
    {
        "space": "engineering",
        "title": "API Versioning Strategy",
        "type": "ADR",
        "content_md": """# ADR: API Versioning Strategy

## Status
Accepted — April 2026

## Context
As Trackly grows its API surface, we need a consistent versioning strategy to ensure backward compatibility and smooth client upgrades.

## Decision
We adopt **URL path versioning** (`/api/v1/`, `/api/v2/`). All breaking changes require a new version prefix. Additive changes (new optional fields, new endpoints) are allowed within the same version.

## Rationale
- URL versioning is explicit and easy to test in browsers and curl
- Avoids header complexity for clients
- Aligns with industry standards used by Stripe, Twilio, and GitHub

## Consequences
- All new endpoints under `/api/` default to v1 behaviour implicitly
- When breaking changes are needed: create `/api/v2/` router and migrate consumers
- Old versions are deprecated with a 6-month sunset notice in the `Deprecation` response header

## Implementation
```python
# FastAPI router setup
v1_router = APIRouter(prefix="/api/v1")
v2_router = APIRouter(prefix="/api/v2")
app.include_router(v1_router)
app.include_router(v2_router)
```

## Review
Next review: October 2026 — assess if versioning overhead justifies continuation.
""",
    },
    {
        "space": "engineering",
        "title": "Auth Middleware Architecture",
        "type": "Runbook",
        "content_md": """# Auth Middleware Architecture — Runbook

## Overview
Trackly uses **JWT HS256** tokens with a 24-hour expiry, validated on every request via FastAPI's `Depends(get_current_user)`.

## Token Structure
```json
{
  "sub": "<user_uuid>",
  "email": "user@example.com",
  "role": "team_member",
  "org_id": "<org_uuid>",
  "pod": "DPAI",
  "exp": 1712345678
}
```

## Middleware Chain
1. `HTTPBearer` extracts the `Authorization: Bearer <token>` header
2. `decode_jwt()` verifies signature + expiry using `python-jose`
3. User is fetched from DB and checked for `status != inactive`
4. User object is injected into route handler via `Depends`

## Role Enforcement
```python
# Admin-only route
@router.get("/admin", dependencies=[Depends(get_admin)])

# Multi-role route
@router.post("/tickets", dependencies=[Depends(require_role("admin", "engineering_manager"))])
```

## Troubleshooting
| Symptom | Cause | Fix |
|---|---|---|
| 401 Invalid token | Token expired or wrong secret | Re-login to get fresh token |
| 401 User not found | User deleted or deactivated | Check user status in DB |
| 403 Forbidden | Wrong role | Check user.role vs required roles |

## Secret Rotation
1. Generate new secret: `openssl rand -hex 32`
2. Update `JWT_SECRET` in `.env`
3. Restart server — all existing tokens invalidated (users must re-login)
4. Announce to team in Slack #engineering
""",
    },
    {
        "space": "engineering",
        "title": "Frontend Architecture Guidelines",
        "type": "Standards",
        "content_md": """# Frontend Architecture Guidelines

## Stack
- **Framework:** React 18 + TypeScript
- **State:** Zustand (lightweight, no boilerplate)
- **Data fetching:** TanStack Query v5 (caching, background refetch)
- **Routing:** React Router v6
- **UI:** Tailwind CSS + shadcn/ui components
- **Rich text:** TipTap

## Folder Structure
```
src/
├── features/       # Feature-sliced architecture — one folder per domain
├── components/ui/  # Shared dumb components (Button, Badge, Drawer)
├── services/api.ts # All API calls in one place
├── store/          # Zustand stores
└── types/          # Shared TypeScript types
```

## Rules
1. **No prop drilling past 2 levels** — use Zustand store or context
2. **API calls only in `services/api.ts`** — never inline `fetch()` in components
3. **Every list page has empty state** — no blank screens
4. **Loading skeleton, not spinner** — use `<Skeleton />` for perceived performance
5. **Error boundaries on every route** — 403/404 pages catch routing errors

## Component Naming
- Pages: `TicketsPage`, `WikiPage`, `SprintPage`
- Drawers: `TicketDrawer`, `UserDrawer`
- Modals: `CreateTicketModal`, `ConfirmDeleteModal`
- Cards: `TicketCard`, `StandupCard`

## Performance
- Virtualise lists > 50 items with `@tanstack/react-virtual`
- Debounce search inputs by 300ms
- Use `React.memo` for Kanban cards (re-render on drag is expensive)
""",
    },
    {
        "space": "engineering",
        "title": "Database Schema Reference",
        "type": "Reference",
        "content_md": """# Database Schema Reference

## Core Tables

### organisations
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| name | TEXT | Company name |
| jira_url | TEXT | Jira instance URL |
| jira_api_token | TEXT | Encrypted at rest |

### users
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| org_id | UUID | FK → organisations |
| email | TEXT | Unique per org |
| role | ENUM | admin/engineering_manager/tech_lead/team_member/finance_viewer |
| pod | TEXT | Comma-separated POD keys |
| reporting_to | TEXT | emp_no of manager |

### jira_tickets
| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| org_id | UUID | FK → organisations |
| jira_key | TEXT | e.g. DPAI-1018 |
| summary | TEXT | Ticket title |
| status | TEXT | Backlog/In Progress/Done etc. |
| story_points | INT | Fibonacci: 1/2/3/5/8/13 |
| is_deleted | BOOL | Soft delete flag |

## AI Tables

### ticket_embeddings
Stores `vector(384)` from `all-MiniLM-L6-v2`. Used for semantic search and duplicate detection via pgvector `<=>` cosine operator.

### wiki_embeddings
Same structure, linked to `wiki_pages`. Enables cross-search over tickets + wiki in a single query.

## Indexes
All org-scoped queries use composite indexes: `(org_id, <filter_column>)` to avoid full scans.

## Migrations
All schema changes via Alembic: `alembic upgrade head`
""",
    },
    {
        "space": "engineering",
        "title": "Rate Limiting Policy",
        "type": "Decision",
        "content_md": """# Rate Limiting Policy

## Decision
Implement **per-user, per-endpoint** rate limiting using a sliding window algorithm, enforced at the FastAPI middleware layer.

## Limits

| Tier | Limit | Window |
|---|---|---|
| Standard (all users) | 300 requests | 60 seconds |
| AI endpoints (/api/nova/*) | 20 requests | 60 seconds |
| Auth endpoints (/api/auth/*) | 10 requests | 60 seconds |
| Export endpoints (/api/export/*) | 5 requests | 300 seconds |

## Implementation Plan
Use `slowapi` (FastAPI-compatible limiter based on `limits`):

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/nova/query")
@limiter.limit("20/minute")
async def nova_query(request: Request, ...):
    ...
```

## Rationale
- NOVA endpoints are CPU-intensive (Ollama inference) — must protect server
- Auth endpoints need brute-force protection
- Export is a heavy DB + XLSX generation operation

## Response on Limit Hit
```json
HTTP 429 Too Many Requests
{ "detail": "Rate limit exceeded. Try again in 45 seconds." }
```

## Monitoring
Log all 429s to `audit_log` with `action = "rate_limited"`. Alert if any user hits > 50 rate limits per hour (possible abuse).
""",
    },
    {
        "space": "dpai",
        "title": "Forecasting Module Technical Design",
        "type": "PRD",
        "content_md": """# Forecasting Module — Technical Design

## Overview
The Forecasting Module enables demand planners at JFL (client) to view, edit, and export demand forecasts across SKUs and distribution zones.

## Core Components

### Data Grid
- Virtual scrolling via AG Grid — handles 10,000+ rows without performance degradation
- Column reorder: drag handle on header, persisted to `localStorage`
- Column visibility: "Manage Columns" drawer with toggle list
- Group by: single column grouping with collapsible rows + subtotals

### DFU Side Drawer
- Opens on row click — shows Distribution Forecast Unit detail
- Tabs: Overview | History | Comments | Adjustments
- Performance fix (DPAI-6856): lazy-load tab content, skeleton placeholders

### Known Bugs (Active)
| Key | Summary | Status |
|---|---|---|
| DPAI-1018 | Drag & drop column reorder broken on Firefox | In Progress |
| DPAI-1015 | JFL UAT environment slow to load DFU drawer | In Progress |
| DPAI-1012 | Group by pagination fails on 2nd page | In Review |

## API Contracts
```
GET  /api/forecasting/data?sku=&zone=&period=
POST /api/forecasting/adjustments
GET  /api/forecasting/export?format=xlsx
```

## Performance Targets
- Initial load < 3s on 10k row dataset
- Column reorder < 100ms
- DFU drawer open < 500ms
""",
    },
    {
        "space": "dpai",
        "title": "JFL UAT Sprint 14 Retrospective",
        "type": "Retro",
        "content_md": """# JFL UAT Sprint 14 — Retrospective

**Date:** April 5, 2026
**Facilitator:** Anand Verma
**Attendees:** Anand Verma, Mohit Kapoor, Prakash Kumar, Achal Kokatanoor

---

## What Went Well ✅
- Fixed 6 critical bugs before UAT sign-off deadline
- DFU drawer performance (DPAI-6856) resolved permanently — no regression in 2 sprints
- QA environment stabilised after nginx config update
- Client feedback turnaround improved from 48h → 24h

## What Didn't Go Well ❌
- DPAI-1015 (slow DFU drawer in UAT) discovered late — missed in dev testing
- Missing test coverage for Firefox-specific drag events
- Sprint planning overcommitted by 8 story points — velocity was 34, planned 42

## Action Items 📋
| Action | Owner | Due |
|---|---|---|
| Add Firefox to cross-browser test matrix | Prakash Kumar | April 14 |
| Write E2E test for DFU drawer load time | Achal Kokatanoor | April 14 |
| Adjust velocity estimate to 34 pts for Sprint 15 | Anand Verma | Sprint planning |
| Add UAT performance benchmark to CI pipeline | Mohit Kapoor | April 17 |

## Sprint Metrics
- **Planned:** 42 points | **Completed:** 34 points | **Velocity:** 81%
- **Bugs fixed:** 6 | **Stories delivered:** 2 | **Carry-over:** 1
""",
    },
    {
        "space": "dpai",
        "title": "DFU Side Drawer Performance Investigation",
        "type": "Incident",
        "content_md": """# Incident: DFU Side Drawer Performance — DPAI-6856

## Summary
The DFU (Distribution Forecast Unit) side drawer in the JFL UAT environment exhibited 4–8 second load times, causing client escalation during UAT session on March 28, 2026.

## Timeline
| Time | Event |
|---|---|
| 14:00 | Client reports drawer taking 6–8s to open |
| 14:15 | Anand Verma confirms on UAT environment |
| 14:30 | Network tab analysis: 3 blocking API calls on drawer open |
| 15:00 | Root cause identified: eager-loading all 3 tabs simultaneously |
| 15:45 | Fix deployed: lazy-load tabs, skeleton loaders added |
| 16:00 | Client confirms drawer now opens in < 800ms |

## Root Cause
On drawer open, the component simultaneously fired:
1. `GET /api/forecasting/dfu/:id` (overview)
2. `GET /api/forecasting/dfu/:id/history?days=90` (heavy — 900ms)
3. `GET /api/forecasting/dfu/:id/adjustments` (300ms)

Only the overview call was needed on initial open.

## Fix
```typescript
// Before: all tabs loaded on mount
useEffect(() => {
  fetchOverview(); fetchHistory(); fetchAdjustments();
}, []);

// After: lazy-load on tab activation
const onTabChange = (tab) => {
  if (tab === "history" && !historyLoaded) fetchHistory();
  if (tab === "adjustments" && !adjustmentsLoaded) fetchAdjustments();
};
```

## Prevention
- Tab components now use `enabled: activeTab === tabKey` in React Query
- Added Lighthouse CI check for drawer open time > 1000ms
""",
    },
    {
        "space": "snop",
        "title": "Turkish Localisation Checklist",
        "type": "Checklist",
        "content_md": """# Turkish Localisation Checklist

Use this checklist before every release that touches UI strings or number formatting.

## String Translations
- [ ] All new UI strings added to `tr.json` locale file
- [ ] No hardcoded English strings in components
- [ ] Button labels fit within button width (Turkish words are longer — test at 1280px)
- [ ] Truncation tested with `...` overflow on long Turkish words
- [ ] SNOP-138 regression check: Edit button not overlapping adjacent controls

## Number & Date Formatting
- [ ] Decimal separator: `,` not `.` (Turkish locale uses comma)
- [ ] Thousand separator: `.` not `,`
- [ ] Date format: `DD.MM.YYYY` (not `MM/DD/YYYY`)
- [ ] Currency: `₺` prefix (Turkish Lira)
- [ ] SNOP-142 regression: number input fields accept Turkish decimal format

## RTL/Layout
- [ ] Turkey uses LTR — no RTL needed, but check for `dir="rtl"` bleed from other locales

## API Responses
- [ ] All dates returned from API in ISO 8601 — formatted client-side
- [ ] Number fields returned as floats — formatted client-side, never pre-formatted in API

## Testing
- [ ] QA ran full regression in `tr-TR` locale
- [ ] Screenshot comparison for key screens vs baseline
- [ ] Client sign-off on Turkish UAT environment
""",
    },
    {
        "space": "snop",
        "title": "Supply Chain Data Model",
        "type": "Reference",
        "content_md": """# Supply Chain Data Model — SNOP

## Core Entities

### Supplier
Represents an external vendor providing raw materials or finished goods.

| Field | Type | Description |
|---|---|---|
| supplier_id | UUID | Primary key |
| name | TEXT | Supplier legal name |
| region | TEXT | Geography: APAC / EMEA / AMER |
| lead_time_days | INT | Average procurement lead time |
| reliability_score | FLOAT | 0.0–1.0 based on on-time delivery % |

### SKU (Stock Keeping Unit)
| Field | Type | Description |
|---|---|---|
| sku_id | TEXT | Client's SKU code |
| description | TEXT | Product description |
| category | TEXT | Product category |
| unit_of_measure | TEXT | EA / KG / L |

### Demand Forecast
| Field | Type | Description |
|---|---|---|
| forecast_id | UUID | Primary key |
| sku_id | TEXT | FK → SKU |
| zone_id | TEXT | Distribution zone |
| period | DATE | Forecast period (month start) |
| quantity | FLOAT | Forecasted demand units |
| confidence | FLOAT | Model confidence 0.0–1.0 |

## Key Relationships
```
Supplier ──< PurchaseOrder >── SKU ──< DemandForecast
                                 └─── InventoryLevel
```

## Demand Sensing
The demand sensing module combines:
1. Historical sales data (12 months)
2. External signals: weather, promotions, market trends
3. NOVA AI adjustment layer (planned for Q3 2026)

## SLA Targets
- Forecast accuracy: MAE < 15%
- Inventory turnover: > 8x per year
- On-time delivery rate: > 95%
""",
    },
    {
        "space": "processes",
        "title": "Engineering On-Call Runbook",
        "type": "Process",
        "content_md": """# Engineering On-Call Runbook

## On-Call Schedule
- Rotation: weekly, Monday 9AM → Monday 9AM
- Coverage: Mon–Fri 9AM–6PM IST (out-of-hours: best effort)
- Handoff: Slack #on-call, update PagerDuty rotation

## Alert Severity Levels

| Level | Response Time | Example |
|---|---|---|
| P0 — Critical | 15 minutes | DB down, auth broken, all users blocked |
| P1 — High | 1 hour | Feature broken for a POD, data incorrect |
| P2 — Medium | 4 hours | Performance degraded, non-critical bug |
| P3 — Low | Next business day | UI glitch, cosmetic issue |

## First Response Checklist
1. Acknowledge alert in PagerDuty (stops escalation)
2. Check `GET /api/health` — is DB + NOVA up?
3. Check logs: `docker logs trackly-api --tail=100`
4. Check DB connections: `SELECT count(*) FROM pg_stat_activity`
5. If unclear — escalate to #engineering-leads immediately

## Common Issues & Fixes

### API returning 500s
```bash
docker logs trackly-api --tail=50
# Look for: sqlalchemy.exc, UnicodeDecodeError, OOM
docker restart trackly-api
```

### DB connection pool exhausted
```sql
SELECT pid, query, state FROM pg_stat_activity WHERE state = 'idle in transaction';
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction';
```

### NOVA (Ollama) not responding
```bash
curl http://localhost:11434/api/tags
ollama serve  # if not running
ollama pull llama3.1:8b  # if model missing
```

## Post-Incident
1. Write incident doc in Wiki → SNOP or Engineering space
2. Create follow-up tickets for root cause fix
3. Update this runbook if a new scenario discovered
""",
    },
    {
        "space": "processes",
        "title": "Code Review Standards",
        "type": "Process",
        "content_md": """# Code Review Standards

## Why We Review
Code review at 3SC is about **knowledge sharing and catching bugs early** — not gatekeeping. Every engineer is expected to both give and receive reviews constructively.

## PR Requirements
- [ ] Branch name: `feature/DPAI-1018-column-reorder` or `fix/SNOP-138-edit-button`
- [ ] PR title matches Jira ticket summary
- [ ] Description includes: what changed, why, how to test
- [ ] Self-review done before requesting others
- [ ] No `console.log` / `print()` debug statements left in
- [ ] Tests added/updated for new functionality
- [ ] No secrets or API keys in diff

## Review SLAs
| PR Size | Review Within |
|---|---|
| < 100 lines | 4 hours |
| 100–500 lines | 1 business day |
| > 500 lines | Break it up! |

## How to Give Good Feedback
- **Nitpick** (optional): `nit: consider extracting this to a helper`
- **Suggestion** (expected to fix): `suggestion: this will fail if list is empty`
- **Blocker** (must fix before merge): `blocker: this causes SQL injection — use parameterised query`

## Merge Rules
- Minimum **1 approval** from a peer
- Tech lead or manager approval required for: auth changes, DB migrations, shared utils
- **Squash merge** only — keeps main history clean
- Delete branch after merge

## Backend Checklist
- [ ] All routes use `Depends(get_current_user)`
- [ ] DB queries filter by `org_id`
- [ ] No raw SQL strings (use ORM or `text()` with bound params)
- [ ] Soft delete for tickets/comments (never hard DELETE)
- [ ] Errors raise `HTTPException`, not bare exceptions
""",
    },
]


def seed_wiki(org_id: str, user_id: str, embed: bool = True):
    db = SessionLocal()
    inserted_spaces = 0
    inserted_pages  = 0
    space_map = {}

    try:
        # Create or find spaces
        for s in SPACES:
            existing = db.query(WikiSpace).filter(
                WikiSpace.org_id == org_id, WikiSpace.slug == s["slug"]
            ).first()
            if existing:
                space_map[s["slug"]] = existing.id
                print(f"  skip space '{s['name']}' (exists)")
                continue

            space = WikiSpace(
                id=gen_uuid(), org_id=org_id,
                name=s["name"], slug=s["slug"],
                description=s["description"], access_level="private",
            )
            db.add(space)
            db.commit()
            db.refresh(space)
            space_map[s["slug"]] = space.id
            inserted_spaces += 1
            print(f"  📁 space: {s['name']}")

        # Create pages
        for p in PAGES:
            space_id = space_map.get(p["space"])
            if not space_id:
                print(f"  ⚠️  space '{p['space']}' not found — skip '{p['title']}'")
                continue

            existing = db.query(WikiPage).filter(
                WikiPage.space_id == space_id, WikiPage.title == p["title"]
            ).first()
            if existing:
                print(f"  skip page '{p['title']}' (exists)")
                continue

            page = WikiPage(
                id=gen_uuid(), space_id=space_id, org_id=org_id,
                title=p["title"], content_md=p["content_md"],
                version=1, author_id=user_id,
            )
            db.add(page)
            db.commit()
            db.refresh(page)
            inserted_pages += 1
            print(f"  ✅ [{p['type']}] {p['title']}")

            if embed:
                try:
                    import asyncio
                    from app.ai.search import embed_and_store_wiki
                    asyncio.run(embed_and_store_wiki(page.id, page.title, page.content_md or "", db))
                    print(f"     🧠 embedded")
                except Exception as e:
                    print(f"     ⚠️  embed failed: {e}")

    finally:
        db.close()

    print(f"\n✅ Seeded {inserted_spaces} spaces + {inserted_pages} pages")
    return inserted_spaces, inserted_pages


if __name__ == "__main__":
    from app.core.database import SessionLocal
    from app.models.organisation import Organisation
    from app.models.user import User
    db = SessionLocal()
    org  = db.query(Organisation).first()
    user = db.query(User).filter(User.org_id == org.id).first() if org else None
    db.close()

    if not org or not user:
        print("❌ No org or user found.")
        sys.exit(1)

    print(f"Seeding wiki for org: {org.name} ({org.id})")
    seed_wiki(org.id, user.id)
