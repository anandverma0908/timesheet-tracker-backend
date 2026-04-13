# 🚀 Trackly — Master Project Tracker
> **The work OS for modern teams.**
> AI-powered KMS replacing Jira + Confluence · Powered by **NOVA AI** (100% local, zero external API)
> 3SC Hackathon 2026 · Jira Track

---

## 📋 Project Meta

| Field | Value |
|---|---|
| **Product** | Trackly — Knowledge Management System |
| **Tagline** | The work OS for modern teams |
| **Built-in AI** | NOVA — Neural Orchestration & Velocity Assistant (Llama 3.1 8B via Ollama, 100% local) |
| **Track** | Jira — 3SC Hackathon 2026 |
| **Stack** | React 18 + TypeScript + FastAPI + PostgreSQL + pgvector + Ollama |
| **Hosting** | Local — Docker Compose |
| **Team** | 2 engineers |
| **Total Tasks** | ~130 tasks across 4 layers |
| **Total Effort** | ~150 hours |
| **Start Date** | April 7, 2026 |
| **Final Deadline** | May 1, 2026 |
| **Demo Day** | May 5–8, 2026 |

---

## 🏁 Phase Gates

| Phase | Deadline | Weight | Status | Deliverable |
|---|---|---|---|---|
| Phase 1: Architecture | April 10, 2026 | 10% | ✅ Done | Architecture doc submitted |
| Phase 2: MVP Demo | April 17, 2026 | 15% | ✅ Done | BE W1–W4 complete · FE in progress |
| Phase 3: Feature Review | April 24, 2026 | 15% | 🔄 In Progress | BE all done · FE W3 in progress |
| Final Submission | May 1, 2026 | 30% | ⬜ Not Started | Complete app, docs, Docker ready |
| Demo Day | May 5–8, 2026 | 30% | ⬜ Not Started | Live demo + Q&A |

---

## 📊 Overall Progress

```
Phase 1 (Architecture)        ████████████████  100% ✅
────────────────────────────────────────────────────────────
🖥️  FE — Week 1  Tickets       ████░░░░░░░░░░░░   1/10
🖥️  FE — Week 2  Wiki+Search   ░░░░░░░░░░░░░░░░   0/10
🖥️  FE — Week 3  Sprint+Kanban ░░░░░░░░░░░░░░░░   0/12
🖥️  FE — Week 4  Polish        ░░░░░░░░░░░░░░░░   0/10
⚙️  BE — Week 1  Tickets+AI    ████████████████  10/10 ✅
⚙️  BE — Week 2  Wiki+Search   ████████████████  10/10 ✅
⚙️  BE — Week 3  Sprint+AI     ████████████████  12/12 ✅
⚙️  BE — Week 4  Notif+Burn    ████████████████  10/10 ✅
🧠  NOVA AI Layer              ████████████████  17/17 ✅
🗄️  DB Migrations              ████████████████  10/10 ✅
🏗️  Infrastructure             ████████░░░░░░░░   5/8
🧪  Testing + Deploy           ░░░░░░░░░░░░░░░░   0/10
────────────────────────────────────────────────────────────
Total                          ████████░░░░░░░░  89/129 (69%)
```

> **How to update:** change `⬜` → `🔄` (in progress) → `✅` (done). Each `█` = ~1 task in that row.

---

## ✅ Already Shipped — Do Not Rebuild

| Module | Details |
|---|---|
| ✅ Auth + JWT + bcrypt | Login, logout, JWT 24h expiry, password hashing |
| ✅ Role-based access | admin, engineering_manager, tech_lead, team_member, finance_viewer |
| ✅ User management | Create, edit, reset password, assign roles + PODs, admin screen |
| ✅ Org hierarchy | 46 engineers, 8 PODs, Keka HR sync, reporting_to chain |
| ✅ Jira ticket sync | Pulls tickets + worklogs from Jira API into PostgreSQL |
| ✅ Time logging | Jira worklogs + manual entries, approval workflow |
| ✅ Dashboard analytics | Hours by POD/client/engineer, issue type split, KPIs |
| ✅ Team page | Engineer cards, drawer with stats, role-scoped |
| ✅ Export reports | Monthly + FY XLSX |
| ✅ Filter system | pods[], clients[], date range — all APIs scoped |
| ✅ Change password | Full-screen, strength meter |
| ✅ Docker Compose base | postgres+pgvector, FastAPI, React |
| ✅ pgvector setup | Extension configured, embedding tables migrated |
| ✅ Alembic migrations v1 | organisations, users, jira_tickets, worklogs, manual_entries |

---

## 🎯 Breakthrough Features (NOVA-powered)

| Feature | Week | Status | Tested |
|---|---|---|---|
| 🧠 NL Ticket Creation — type a sentence, NOVA builds the full ticket | W1 | ✅ | ⬜ |
| 🧠 AI Daily Standup Generator — auto-generated at 9AM from each engineer's worklogs | W3 | ✅ | ⬜ |
| 🧠 Client Hour Burn Rate Alert — NOVA alerts PM + Finance at 70/85/100/110% | W4 | ✅ | ⬜ |

---

---

# 🧠 NOVA AI — Built-in Intelligence Layer

> **NOVA** = Neural Orchestration & Velocity Assistant
> Runs 100% locally on Llama 3.1 8B via Ollama.
> No OpenAI. No Claude. No external APIs. Your data never leaves your server.

---

## NOVA Setup (one-time)

```bash
# 1. Install Ollama
brew install ollama          # macOS
curl -fsSL https://ollama.com/install.sh | sh   # Linux

# 2. Start and pull model (~4.7GB, one time)
ollama serve
ollama pull llama3.1:8b

# 3. Verify
ollama run llama3.1:8b "Hello NOVA, are you running?"
```

---

## NOVA Docker Compose Service

```yaml
# Add to docker-compose.yml
ollama:
  image: ollama/ollama
  ports:
    - "11434:11434"
  volumes:
    - ollama_data:/root/.ollama

ollama-init:
  image: ollama/ollama
  depends_on: [ollama]
  command: sh -c "sleep 5 && ollama pull llama3.1:8b"
  environment:
    - OLLAMA_HOST=ollama:11434

volumes:
  ollama_data:
```

---

## NOVA Environment Variables

```env
NOVA_MODEL=llama3.1:8b
NOVA_BASE_URL=http://ollama:11434
EMBEDDING_MODEL=all-MiniLM-L6-v2
NOVA_TEMPERATURE=0.3
NOVA_MAX_TOKENS=1500
```

---

## NOVA Backend Files

| File | Purpose | Status |
|---|---|---|
| `backend/ai/nova.py` | Core engine — Ollama chat, embeddings, reranker | ✅ Done |
| `backend/ai/ticket_intelligence.py` | Agentic flow — NL→fields, duplicate check, classify | ✅ Done |
| `backend/ai/search.py` | pgvector cosine search, RAG pipeline | ✅ Done |
| `backend/ai/documents.py` | Sprint retro, release notes, meeting→actions, standup | ✅ Done |
| `backend/ai/knowledge_gaps.py` | TF-IDF clustering + wiki coverage check | ✅ Done |
| `backend/routes/nova.py` | All `/api/nova/` endpoints | ✅ Done |

---

## NOVA AI Feature Tracker

| # | Feature | Endpoint | Week | Status | Tested |
|---|---|---|---|---|---|
| AI-1 | Ticket embedding on create/update | Internal | W1 | ✅ | ⬜ |
| AI-2 | Wiki page embedding on create/update | Internal | W2 | ✅ | ⬜ |
| AI-3 | Duplicate detection — pgvector similarity > 0.85 | POST /api/tickets/ai-analyze | W1 | ✅ | ⬜ |
| AI-4 | Smart labeling — NOVA extracts POD, client, type, priority | POST /api/tickets/ai-analyze | W1 | ✅ | ⬜ |
| AI-5 | Effort estimation — NOVA estimates story points 1/2/3/5/8/13 | POST /api/tickets/ai-analyze | W1 | ✅ | ⬜ |
| AI-6 | Assignee suggestion — pattern match from past tickets | POST /api/tickets/ai-analyze | W1 | ✅ | ⬜ |
| AI-7 | NL ticket creation — NOVA extracts all fields from a sentence | POST /api/tickets/nl-create | W1 | ✅ | ⬜ |
| AI-8 | Semantic search — pgvector cosine across tickets + wiki | POST /api/search | W2 | ✅ | ⬜ |
| AI-9 | NL query RAG — retrieve docs + NOVA synthesis + citations | POST /api/nova/query | W2 | ✅ | ⬜ |
| AI-10 | Related docs auto-suggest — pgvector top 5 per ticket/page | GET /api/*/related | W2 | ✅ | ⬜ |
| AI-11 | Meeting notes → action items — NOVA extraction | POST /api/wiki/ai/meeting-notes | W2 | ✅ | ⬜ |
| AI-12 | Sprint retro generation — NOVA summarises Done tickets | POST /api/nova/sprint-retro/:id | W3 | ✅ | ⬜ |
| AI-13 | Release notes generation — NOVA aggregates Done tickets | POST /api/nova/release-notes/:id | W3 | ✅ | ⬜ |
| AI-14 | Knowledge gap detection — TF-IDF cluster vs wiki coverage | Background job (weekly) | W3 | ✅ | ⬜ |
| AI-15 | Daily standup generator — NOVA generates from worklogs at 9AM | POST /api/nova/standup/generate | W3 | ✅ | ⬜ |
| AI-16 | AI process assistant — RAG over wiki pages only | POST /api/nova/query?scope=wiki | W3 | ✅ | ⬜ |
| AI-17 | Burn rate AI summary — NOVA projects budget trend + ETA | GET /api/clients/burn-rate | W4 | ✅ | ⬜ |

---

## NOVA Prompt Templates

> Store all prompts in `backend/ai/prompts.py`

| Constant | Purpose | Input | Output |
|---|---|---|---|
| `TICKET_CLASSIFY` | Extract fields from NL input | Raw text | JSON: title, pod, client, type, priority, pts, assignee |
| `DUPLICATE_WARN` | Summarise similar ticket for warning | Ticket A + similar list | "Similar to DPAI-1021 (87%): ..." |
| `EFFORT_ESTIMATE` | Estimate story points | Title + description | JSON: points, reasoning |
| `NL_QUERY_ANSWER` | Synthesise RAG answer | Query + top-N docs | Answer + citations list |
| `SPRINT_RETRO` | Generate sprint retro | Done tickets + stats | What went well / Delta / Actions |
| `RELEASE_NOTES` | Generate changelog | Done tickets grouped by type | Features / Bug Fixes / Improvements |
| `STANDUP_GENERATE` | Generate standup | Yesterday worklogs + today tickets | Yesterday / Today / Blockers |
| `BURNRATE_SUMMARY` | Project budget trend | Hours used, budget, days left | NL summary with projection date |
| `GAP_DESCRIPTION` | Describe a knowledge gap | Topic cluster label | "No docs found for X. Consider creating Y." |
| `MEETING_ACTIONS` | Extract action items | Raw meeting notes | Structured: action, owner, due date |

---

---

# 🖥️ FRONTEND TASKS

---

## FE — Week 1: Ticket Management
> **Deadline: April 17** | Owner: FE Engineer

| # | Task | Priority | Est | Status | Notes |
|---|---|---|---|---|---|
| FE-1.1 | Ticket creation form — all fields (title, desc, assignee, POD, client, type, priority, story pts, sprint, labels, due date) | P0 | 5h | 🔄 In Progress | |
| FE-1.2 | NL ticket creation — text input triggers NOVA, pre-fills form with suggestions + confidence scores | P0 | 4h | ⬜ | Calls `/api/tickets/nl-create` |
| FE-1.3 | Duplicate warning panel — shows similar tickets before save | P0 | 2h | ⬜ | Threshold: similarity > 0.85 |
| FE-1.4 | Ticket detail drawer — key, title, status, meta sidebar, description (rich text), worklog, comments, attachments, activity | P0 | 6h | ⬜ | Side drawer on list click, full page on direct URL |
| FE-1.5 | Inline field editing — click any field to edit, save on blur | P0 | 3h | ⬜ | |
| FE-1.6 | Status transition UI — status pill dropdown with allowed transitions per role | P0 | 2h | ⬜ | |
| FE-1.7 | Comment thread — threaded comments, reply, @mention dropdown, rich text, reactions | P1 | 4h | ⬜ | |
| FE-1.8 | File attachment — drag-drop upload, image preview, file list | P1 | 3h | ⬜ | |
| FE-1.9 | Activity log in ticket drawer — status changes, reassignments, edits with timestamps | P1 | 2h | ⬜ | |
| FE-1.10 | Ticket list page — sortable columns, filter bar, pagination | P0 | 3h | ⬜ | Extend existing TicketsPage |

**FE Week 1 Total:** ~34h | Done: 1/10

---

## FE — Week 2: Wiki + Search UI
> **Deadline: April 17** | Owner: FE Engineer

| # | Task | Priority | Est | Status | Notes |
|---|---|---|---|---|---|
| FE-2.1 | Wiki sidebar — spaces list, expandable pages tree, active page highlight | P0 | 4h | ⬜ | |
| FE-2.2 | TipTap rich text editor — Markdown shortcuts, bold/italic/code, tables, task lists, callout blocks | P0 | 5h | ⬜ | Install: `@tiptap/react` |
| FE-2.3 | TipTap TicketLink extension — type `/ticket DPAI-123` to embed linked ticket card | P0 | 3h | ⬜ | |
| FE-2.4 | TipTap PageLink extension — type `/page` to link to another wiki page | P0 | 2h | ⬜ | |
| FE-2.5 | Auto-save indicator — saves to backend every 30s, shows "Saving…" / "Saved" | P0 | 1h | ⬜ | |
| FE-2.6 | Page version history panel — list of versions, diff view, restore button | P0 | 3h | ⬜ | |
| FE-2.7 | Search modal — Cmd+K shortcut, semantic results list, NOVA answer panel with citations | P0 | 4h | ⬜ | Show "Powered by NOVA" badge |
| FE-2.8 | Related docs widget — auto-suggest on ticket/page view (sidebar) | P0 | 2h | ⬜ | |
| FE-2.9 | Page templates picker — PRD, Runbook, Sprint Retro, Meeting Notes, ADR | P1 | 2h | ⬜ | |
| FE-2.10 | Breadcrumb navigation — Space > Page > Sub-page trail | P0 | 1h | ⬜ | |

**FE Week 2 Total:** ~27h | Done: 0/10

---

## FE — Week 3: Sprint, Kanban, Analytics + AI UI
> **Deadline: April 24** | Owner: FE Engineer

| # | Task | Priority | Est | Status | Notes |
|---|---|---|---|---|---|
| FE-3.1 | Kanban board — columns = workflow stages, drag-drop via @dnd-kit | P0 | 8h | ⬜ | Install: `@dnd-kit/core @dnd-kit/sortable` |
| FE-3.2 | Kanban swimlanes — toggle: No grouping / By Assignee / By Priority / By Epic | P0 | 3h | ⬜ | |
| FE-3.3 | Kanban card — key, title, avatar, priority, story pts, type badge, quick-edit assignee | P0 | 2h | ⬜ | |
| FE-3.4 | Backlog view — split screen: backlog left, sprint right, drag tickets between sides | P0 | 4h | ⬜ | |
| FE-3.5 | Sprint planning view — capacity bar fills as points added, filter backlog | P0 | 3h | ⬜ | |
| FE-3.6 | Burndown chart — ideal line vs actual, hover tooltip, scope change step | P1 | 3h | ⬜ | Recharts |
| FE-3.7 | Velocity chart — story points per sprint, bar chart | P1 | 2h | ⬜ | |
| FE-3.8 | Knowledge gap widget — list of undocumented topics, create wiki stub button | P0 | 2h | ⬜ | |
| FE-3.9 | NOVA process assistant chat widget — fixed bottom-right, RAG responses with citations, "Powered by NOVA" badge | P0 | 4h | ⬜ | |
| FE-3.10 | Daily standup dashboard — manager view: grid of all team standups, filter by POD | P0 | 3h | ⬜ | |
| FE-3.11 | Engineer standup view — own standup card, edit before share button | P0 | 2h | ⬜ | |
| FE-3.12 | Workload distribution chart — hours by engineer bar chart | P1 | 2h | ⬜ | |

**FE Week 3 Total:** ~38h | Done: 0/12

---

## FE — Week 4: Polish, Notifications, Mobile
> **Deadline: May 1** | Owner: FE Engineer

| # | Task | Priority | Est | Status | Notes |
|---|---|---|---|---|---|
| FE-4.1 | Notification bell — unread badge, dropdown list, mark as read, click-to-navigate | P1 | 4h | ⬜ | |
| FE-4.2 | Notification preferences screen — per-type toggles for in-app + email | P1 | 2h | ⬜ | |
| FE-4.3 | Client budget admin screen — set monthly hour budget per client | P0 | 2h | ⬜ | Breakthrough feature |
| FE-4.4 | Burn rate dashboard — progress bars per client, NOVA summary, alert history | P0 | 3h | ⬜ | |
| FE-4.5 | Onboarding flow — 3 steps: change password, see team, create first ticket tutorial | P1 | 4h | ⬜ | |
| FE-4.6 | Mobile responsive — sidebar hamburger, stacked KPIs, single-column kanban, bottom-sheet drawer | P2 | 5h | ⬜ | |
| FE-4.7 | Empty states — every list/chart has icon + message + CTA | P0 | 2h | ⬜ | |
| FE-4.8 | Error boundaries — 403/404 pages, toast error messages, retry buttons | P0 | 2h | ⬜ | |
| FE-4.9 | Timer widget in topbar — ticket selector, HH:MM:SS display, stop → log modal | P0 | 3h | ⬜ | |
| FE-4.10 | Bulk time entry weekly grid — rows = sprint tickets, cols = Mon–Fri, Tab navigation | P1 | 4h | ⬜ | |

**FE Week 4 Total:** ~31h | Done: 0/10

---

## 📦 Frontend Packages to Install

```bash
npm install @tiptap/react @tiptap/starter-kit @tiptap/extension-link \
  @tiptap/extension-image @tiptap/extension-code-block-lowlight \
  @tiptap/extension-table @tiptap/extension-task-list \
  @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities \
  lowlight react-hot-toast date-fns
```

---

## 📁 Frontend File Structure

```
src/
├── features/
│   ├── auth/           ✅ Done
│   ├── dashboard/      ✅ Done — extend with burn rate + NOVA status widget
│   ├── tickets/        🔄 Extend — add create modal, detail drawer
│   ├── kanban/         ⬜ New — KanbanBoard, KanbanColumn, TicketCard
│   ├── sprint/         ⬜ New — SprintPage, BacklogView, BurndownChart
│   ├── wiki/           ⬜ New — WikiSidebar, PageEditor (TipTap), VersionHistory
│   ├── search/         ⬜ New — SearchModal (Cmd+K), NLQueryBox, SemanticResults
│   ├── team/           ✅ Done — extend with standup views
│   ├── standup/        ⬜ New — StandupCard, TeamStandupDashboard
│   ├── timetrack/      🔄 Extend — add timer widget, bulk weekly grid
│   ├── analytics/      🔄 Extend — burndown, velocity, workload charts
│   └── settings/       ✅ Done — extend with client budget screen
├── components/
│   ├── ui/             ✅ Done — DataTable, SideDrawer, Badge, Skeleton
│   └── nova/           ⬜ New — NovaBadge, NovaChatWidget, NovaStatusPill
├── services/api.ts     🔄 Extend — add wiki, sprint, search, standup, nova endpoints
├── store/index.ts      🔄 Extend — add wikiStore, sprintStore
└── types/index.ts      🔄 Extend — add Wiki, Sprint, Standup, Nova types
```

---

---

# ⚙️ BACKEND TASKS

---

## BE — Week 1: Ticket CRUD + NOVA Analysis ✅ COMPLETE
> **Completed: April 12, 2026** | Owner: BE Engineer

| # | Task | Priority | Est | Status | Notes |
|---|---|---|---|---|---|
| BE-1.1 | Ticket CRUD endpoints — POST/PUT/DELETE /api/tickets | P0 | 4h | ✅ | routes/tickets.py |
| BE-1.2 | NL ticket creation — POST /api/tickets/nl-create — NOVA extracts all fields from text | P0 | 4h | ✅ | full_analysis() in ticket_intelligence.py |
| BE-1.3 | AI ticket analysis — POST /api/tickets/ai-analyze — labels, pts, assignee suggestion, duplicates | P0 | 4h | ✅ | Returns fields + duplicates |
| BE-1.4 | Duplicate detection — pgvector similarity search vs open tickets, threshold 0.85 | P0 | 3h | ✅ | find_similar_tickets() in search.py |
| BE-1.5 | Status transition endpoint + history log | P0 | 2h | ✅ | POST /api/tickets/:id/status + audit_log |
| BE-1.6 | Comment CRUD — POST/GET/DELETE /api/tickets/:id/comments | P1 | 3h | ✅ | Threaded (parent_id) |
| BE-1.7 | File attachment upload — POST /api/tickets/:id/attachments | P1 | 3h | ✅ | Stored in /uploads/ |
| BE-1.8 | Activity log endpoint — GET /api/tickets/:id/activity | P1 | 2h | ✅ | Reads audit_log table |
| BE-1.9 | Embedding pipeline — auto-embed ticket on create/update | P0 | 2h | ✅ | BackgroundTask → embed_and_store_ticket() |
| BE-1.10 | NOVA status + query endpoints | P1 | 2h | ✅ | GET /api/nova/status · POST /api/nova/query |

**BE Week 1 Total:** ~29h | Done: 10/10 ✅

---

## BE — Week 2: Wiki + Semantic Search ✅ COMPLETE
> **Completed: April 12, 2026** | Owner: BE Engineer

| # | Task | Priority | Est | Status | Notes |
|---|---|---|---|---|---|
| BE-2.1 | Wiki models — wiki_spaces, wiki_pages, wiki_versions, wiki_embeddings (Alembic migration) | P0 | 2h | ✅ | 002_week2_wiki_tables.py |
| BE-2.2 | Wiki space CRUD — GET/POST/PUT/DELETE /api/wiki/spaces | P0 | 2h | ✅ | routes/wiki.py |
| BE-2.3 | Wiki page CRUD — GET/POST/PUT/DELETE /api/wiki/pages | P0 | 3h | ✅ | Auto-version on PUT |
| BE-2.4 | Version history — GET /api/wiki/pages/:id/versions + POST restore | P0 | 2h | ✅ | Full version snapshots |
| BE-2.5 | Wiki embedding pipeline — auto-embed page on create/edit | P0 | 2h | ✅ | BackgroundTask → embed_and_store_wiki() |
| BE-2.6 | Semantic search — POST /api/search — cosine similarity across tickets + wiki | P0 | 4h | ✅ | routes/search.py — pgvector + reranker |
| BE-2.7 | NL query RAG — POST /api/nova/query — retrieve docs + NOVA synthesis + citations | P0 | 5h | ✅ | Already in routes/nova.py |
| BE-2.8 | Related docs — GET /api/wiki/pages/:id/related | P0 | 2h | ✅ | pgvector similarity, top 5 |
| BE-2.9 | Meeting notes → actions — POST /api/wiki/ai/meeting-notes | P1 | 2h | ✅ | NOVA JSON extraction |
| BE-2.10 | Seed data script — 35 tickets + 12 wiki pages + all embeddings | P0 | 3h | ✅ | seeds/seed_all.py |

**BE Week 2 Total:** ~27h | Done: 10/10 ✅

---

## BE — Week 3: Sprint + NOVA Features + Analytics ✅ COMPLETE
> **Completed: April 12, 2026** | Owner: BE Engineer

| # | Task | Priority | Est | Status | Notes |
|---|---|---|---|---|---|
| BE-3.1 | Sprint models — sprints, standups, knowledge_gaps tables (Alembic migration) | P0 | 1h | ✅ | 003_week3_sprints_standups.py |
| BE-3.2 | Sprint CRUD — GET/POST /api/sprints, GET /api/sprints/:id, start, complete | P0 | 3h | ✅ | routes/sprints.py |
| BE-3.3 | Burndown data — GET /api/sprints/:id/burndown | P1 | 2h | ✅ | Daily ideal vs actual |
| BE-3.4 | Velocity data — GET /api/sprints/:id/velocity | P1 | 1h | ✅ | Historical sprint velocities |
| BE-3.5 | NOVA sprint retro — POST /api/nova/sprint-retro/:id | P1 | 3h | ✅ | ai/documents.py + nova route |
| BE-3.6 | NOVA release notes — POST /api/nova/release-notes/:id | P1 | 2h | ✅ | ai/documents.py + nova route |
| BE-3.7 | Knowledge gap detection — background job (weekly Mon 8AM) | P1 | 4h | ✅ | ai/knowledge_gaps.py + scheduler |
| BE-3.8 | Knowledge gaps endpoint — GET /api/nova/knowledge-gaps + POST /detect | P1 | 1h | ✅ | nova route |
| BE-3.9 | NOVA process assistant — POST /api/nova/query?scope=wiki | P0 | 2h | ✅ | Existing nova query with wiki scope |
| BE-3.10 | Daily standup generator — 9AM APScheduler + POST /api/nova/standup/generate | P0 | 4h | ✅ | ai/documents.py + scheduler |
| BE-3.11 | Standup endpoints — today, team, PUT standup/:id | P0 | 2h | ✅ | nova route |
| BE-3.12 | Analytics endpoints — GET /api/analytics/workload, /pod-summary, /velocity | P1 | 1h | ✅ | routes/analytics.py |

**BE Week 3 Total:** ~26h | Done: 12/12 ✅

---

## BE — Week 4: Notifications + Burn Rate + Polish ✅ COMPLETE
> **Completed: April 12, 2026** | Owner: BE Engineer

| # | Task | Priority | Est | Status | Notes |
|---|---|---|---|---|---|
| BE-4.1 | Notification model — notifications + client_budgets + burn_rate_alerts tables | P1 | 1h | ✅ | 004_week4_notifications_budgets.py |
| BE-4.2 | Notification endpoints — GET /api/notifications, read-all, /:id/read | P1 | 2h | ✅ | routes/notifications.py |
| BE-4.3 | Notification triggers — sprint start, standup ready, burn rate alert | P1 | 3h | ✅ | Wired in sprints + scheduler jobs |
| BE-4.4 | Email notifications — SMTP via smtplib (Mailhog dev) | P1 | 3h | ⬜ | Deferred — in-app notifications complete |
| BE-4.5 | Client budget model — client_budgets + burn_rate_alerts tables | P0 | 1h | ✅ | models/client.py |
| BE-4.6 | Burn rate endpoints — GET /api/clients/burn-rate, POST /api/clients/budget, GET /alerts | P0 | 2h | ✅ | routes/clients.py |
| BE-4.7 | Burn rate alerts — hourly APScheduler job, fires at 70/85/100/110% | P0 | 3h | ✅ | jobs/scheduler.py _burnrate_job() |
| BE-4.8 | Burn rate NOVA summary — NOVA generates NL trend + projection per alert | P0 | 2h | ✅ | Inline in _burnrate_job() |
| BE-4.9 | pgvector IVFFlat index — conditional on row count ≥ 100 | P0 | 2h | ✅ | In 004 migration |
| BE-4.10 | Analytics endpoints — pod-summary, velocity, workload | P0 | 3h | ✅ | routes/analytics.py |

**BE Week 4 Total:** ~22h | Done: 9/10 (email deferred)

---

## 📁 Backend File Structure

```
backend/
├── main.py                    ✅ Done — new routers registered
├── auth.py                    ✅ Done
├── database.py                ✅ Done — TicketComment, TicketAttachment, TicketEmbedding, AuditLog added
├── models.py                  ✅ Done — all W1+W2 Pydantic schemas added
├── ai/
│   ├── nova.py                ✅ Done — NOVA core (Ollama chat, embeddings, reranker)
│   ├── ticket_intelligence.py ✅ Done — NL create, agentic analysis, duplicate check
│   ├── search.py              ✅ Done — pgvector queries, cosine similarity, RAG
│   ├── documents.py           ✅ Done — retro, release notes, standup, meeting→actions
│   └── knowledge_gaps.py      ✅ Done — TF-IDF clustering, wiki coverage check
├── routes/
│   ├── nova.py                ✅ Done — status, query, retro, release notes, standup, gaps
│   ├── tickets.py             ✅ Done — full CRUD + comments + attachments + activity
│   ├── wiki.py                ✅ Done — spaces, pages, versions, related, AI meeting notes
│   ├── search.py              ✅ Done — POST /api/search
│   ├── sprints.py             ✅ Done — full lifecycle + burndown + velocity
│   ├── notifications.py       ✅ Done — list, read-all, read single
│   ├── clients.py             ✅ Done — budget CRUD + burn rate + alerts
│   └── analytics.py           ✅ Done — workload, pod-summary, velocity
├── jobs/
│   └── scheduler.py           ✅ Done — jira sync, standup 9AM, burnrate hourly, gaps weekly
├── seeds/
│   ├── seed_tickets.py        ✅ Done — 35 tickets
│   ├── seed_wiki.py           ✅ Done — 12 wiki pages
│   └── seed_all.py            ✅ Done — runs all seeds + generates embeddings
└── alembic/versions/
    ├── 001_week1_ticket_tables.py  ✅ Done — ticket_embeddings, comments, attachments, audit_log
    ├── 002_week2_wiki_tables.py    ✅ Done — wiki_spaces, wiki_pages, wiki_versions, wiki_embeddings
    ├── 003_week3_sprints_standups.py ✅ Done — sprints, standups, knowledge_gaps
    └── 004_week4_notifications_budgets.py ✅ Done — notifications, client_budgets, burn_rate_alerts, IVFFlat indexes
```

---

## 📦 Backend Packages to Install

```txt
# Add to requirements.txt
ollama==0.3.3
sentence-transformers==3.0.1
torch==2.4.0
scikit-learn==1.5.1
numpy==1.26.4
httpx==0.27.2
apscheduler==3.10.4
python-multipart==0.0.12
```

---

---

# 🗄️ DATABASE / INFRASTRUCTURE TASKS

---

## DB — Migrations (Alembic)

| # | Migration | Tables | Week | Status |
|---|---|---|---|---|
| DB-1 | Initial schema | organisations, users, jira_tickets, worklogs, manual_entries | Done | ✅ |
| DB-2 | pgvector + ticket_embeddings | ticket_embeddings | Done | ✅ |
| DB-3 | Wiki tables | wiki_spaces, wiki_pages, wiki_versions, wiki_embeddings | W2 | ✅ |
| DB-4 | Sprint tables | sprints, standups, knowledge_gaps | W3 | ✅ |
| DB-5 | Comments + attachments | ticket_comments, ticket_attachments | W1 | ✅ |
| DB-6 | Notifications + budgets | notifications, client_budgets, burn_rate_alerts | W4 | ✅ |
| DB-7 | Audit log | audit_log | W4 | ⬜ |
| DB-8 | Client budgets + alerts | client_budgets, burn_rate_alerts | W4 | ⬜ |
| DB-9 | Standups | standups | W3 | ⬜ |
| DB-10 | pgvector IVFFlat index | ticket_embeddings, wiki_embeddings | W4 | ⬜ |

---

## DB — New Table Schemas

```sql
-- Week 1: Comments + Attachments
CREATE TABLE ticket_comments (
  id UUID PRIMARY KEY, ticket_id UUID REFERENCES jira_tickets(id),
  author_id UUID REFERENCES users(id), body TEXT, parent_id UUID,
  created_at TIMESTAMP, updated_at TIMESTAMP, is_deleted BOOLEAN DEFAULT false
);
CREATE TABLE ticket_attachments (
  id UUID PRIMARY KEY, ticket_id UUID REFERENCES jira_tickets(id),
  filename TEXT, filepath TEXT, size_bytes INTEGER,
  uploaded_by UUID REFERENCES users(id), created_at TIMESTAMP
);

-- Week 2: Wiki
CREATE TABLE wiki_spaces (
  id UUID PRIMARY KEY, org_id UUID, name TEXT, slug TEXT,
  description TEXT, access_level TEXT DEFAULT 'private', created_at TIMESTAMP
);
CREATE TABLE wiki_pages (
  id UUID PRIMARY KEY, space_id UUID REFERENCES wiki_spaces(id),
  parent_id UUID, title TEXT, content_md TEXT, content_html TEXT,
  version INTEGER DEFAULT 1, author_id UUID REFERENCES users(id),
  created_at TIMESTAMP, updated_at TIMESTAMP
);
CREATE TABLE wiki_versions (
  id UUID PRIMARY KEY, page_id UUID REFERENCES wiki_pages(id),
  version INTEGER, content_md TEXT, author_id UUID, created_at TIMESTAMP
);
CREATE TABLE wiki_embeddings (
  id UUID PRIMARY KEY, page_id UUID REFERENCES wiki_pages(id),
  embedding vector(384), content_snippet TEXT, updated_at TIMESTAMP
);

-- Week 3: Sprints + Standups
CREATE TABLE sprints (
  id UUID PRIMARY KEY, org_id UUID, project_id UUID,
  name TEXT, goal TEXT, start_date DATE, end_date DATE,
  status TEXT DEFAULT 'planning', velocity INTEGER, created_at TIMESTAMP
);
CREATE TABLE standups (
  id UUID PRIMARY KEY, user_id UUID REFERENCES users(id),
  date DATE, yesterday TEXT, today TEXT, blockers TEXT,
  is_shared BOOLEAN DEFAULT false, generated_at TIMESTAMP
);

-- Week 4: Notifications + Budgets + Audit
CREATE TABLE notifications (
  id UUID PRIMARY KEY, user_id UUID REFERENCES users(id),
  type TEXT, title TEXT, body TEXT, link TEXT,
  is_read BOOLEAN DEFAULT false, created_at TIMESTAMP
);
CREATE TABLE client_budgets (
  id UUID PRIMARY KEY, org_id UUID, client TEXT,
  month INTEGER, year INTEGER, budget_hours NUMERIC, created_at TIMESTAMP
);
CREATE TABLE burn_rate_alerts (
  id UUID PRIMARY KEY, org_id UUID, client TEXT,
  threshold_pct INTEGER, hours_used NUMERIC, hours_budget NUMERIC,
  nova_summary TEXT, notified_at TIMESTAMP
);
CREATE TABLE audit_log (
  id UUID PRIMARY KEY, entity_type TEXT, entity_id UUID,
  user_id UUID, action TEXT, diff_json JSONB, created_at TIMESTAMP
);
```

---

## Infrastructure Tasks

| # | Task | Week | Status | Notes |
|---|---|---|---|---|
| INF-1 | Docker Compose — postgres+pgvector, FastAPI, React, nginx | Done | ✅ | |
| INF-2 | Ollama service in Docker Compose + llama3.1:8b pull on init | W1 | ⬜ | `ollama/ollama` image |
| INF-3 | APScheduler in FastAPI — 9AM standup, hourly burn rate, weekly gaps | W3 | ⬜ | |
| INF-4 | Mailhog container for dev email testing | W4 | ⬜ | Add to docker-compose.yml |
| INF-5 | Nginx reverse proxy — /api → FastAPI, / → React build | W4 | ⬜ | |
| INF-6 | sentence-transformers model baked into Docker image at build | W2 | ⬜ | Avoids runtime download delay |
| INF-7 | Health check — GET /api/health — returns DB + pgvector + NOVA status | W1 | ⬜ | |
| INF-8 | Upload directory setup — /uploads/ with UUID filenames | W1 | ⬜ | |

---

## Environment Variables

```env
# backend/.env
DATABASE_URL=postgresql://trackly:trackly@postgres:5432/trackly
JWT_SECRET=                         # openssl rand -hex 32
EMBEDDING_MODEL=all-MiniLM-L6-v2

# NOVA AI — 100% local, no external API keys needed
NOVA_MODEL=llama3.1:8b
NOVA_BASE_URL=http://ollama:11434
NOVA_TEMPERATURE=0.3
NOVA_MAX_TOKENS=1500

# Email (dev only)
SMTP_HOST=mailhog
SMTP_PORT=1025

# frontend/.env
VITE_API_URL=http://localhost:8000
```

---

---

# 🌱 SEED DATA CHECKLIST

---

## Projects (2)
- [ ] DPAI — Demand Planning AI (20 tickets)
- [ ] SNOP — Supply Network Optimisation (15 tickets)

## Tickets (35 total)

### DPAI Project (20 tickets)
- [ ] DPAI-1018 Forecasting UI drag & drop — Story — In Progress — Anand Verma
- [ ] DPAI-1015 JFL UAT slow load — Bug — In Progress — Mohit Kapoor
- [ ] DPAI-1012 Group by pagination — Bug — In Review — Prakash Kumar
- [ ] DPAI-1010 Analytics dashboard redesign — Epic — In Review — Anand Verma
- [ ] DPAI-1009 Login page redesign — Task — Done — Anand Verma
- [ ] DPAI-7018 Data grid scroll fix — Bug — Done — Anand Verma
- [ ] DPAI-7013 Drag & drop column fix — Bug — Done — Prakash Kumar
- [ ] DPAI-7011 Unnecessary API call fix — Bug — Done — Anand Verma
- [ ] DPAI-7000 Data grid display fix — Bug — Done — Anand Verma
- [ ] DPAI-6972 Manage column rearrangement — Bug — Done — Prakash Kumar
- [ ] DPAI-6971 Manage column dropdown fix — Bug — Done — Anand Verma
- [ ] DPAI-6856 DFU side drawer lag — Bug — Done — Anand Verma
- [ ] DPAI-1021 Auth middleware refactor — Story — Backlog — Anand Verma
- [ ] DPAI-1022 Rate limiting APIs — Task — Backlog — Prakash Kumar
- [ ] DPAI-1019 Mobile responsive — Bug — Backlog — Achal Kokatanoor
- [ ] DPAI-1020 Dark mode support — Story — Backlog — Mohit Kapoor
- [ ] DPAI-1023 Export to Excel — Task — Backlog — Swapnil Akash
- [ ] DPAI-1024 Performance profiling — Task — Backlog — Prakash Kumar
- [ ] DPAI-1025 Jest unit tests — Task — Backlog — Anand Verma
- [ ] DPAI-1026 API docs cleanup — Task — Backlog — Mohit Kapoor

### SNOP Project (15 tickets)
- [ ] SNOP-138 Turkish language overlap — Bug — In Review — Anand Verma
- [ ] SNOP-139 SLA alerts not firing — Bug — In Progress — Aman Kumar Singh
- [ ] SNOP-140 Sprint capacity view — Story — In Progress — Akash Kumar
- [ ] SNOP-141 Vendor scorecard — Epic — Backlog — Ishu Rani
- [ ] SNOP-108 Filter panel overlap — Bug — Done — Anand Verma
- [ ] SNOP-109 Blank page pagination — Bug — Done — Anand Verma
- [ ] SNOP-113 Demand sensing error — Bug — Done — Anand Verma
- [ ] SNOP-142 Turkish number formatting — Bug — Backlog — Akanksha
- [ ] SNOP-143 Export to PDF — Task — Backlog — Ashish Kumar Gopalika
- [ ] SNOP-144 ERP integration — Epic — Backlog — Anoop Kumar Rai
- [ ] SNOP-145 Bulk import suppliers — Story — Backlog — Aastha Rai
- [ ] SNOP-146 Real-time stock dashboard — Story — Backlog — Akash Kumar
- [ ] SNOP-147 AI demand forecasting backtest — Epic — Backlog — Prakash Kumar
- [ ] SNOP-148 Low stock alerts — Story — Backlog — Mohit Kapoor
- [ ] SNOP-149 Role-based supply chain view — Story — Backlog — Aman Kumar Singh

## Wiki Pages (12 total)
- [ ] Engineering / API Versioning Strategy (ADR)
- [ ] Engineering / Auth Middleware Architecture (Runbook)
- [ ] Engineering / Frontend Architecture Guidelines (Standards)
- [ ] Engineering / Database Schema Reference (Reference)
- [ ] Engineering / Rate Limiting Policy (Decision record)
- [ ] DPAI / Forecasting Module Technical Design (PRD)
- [ ] DPAI / JFL UAT Sprint 14 Retrospective (Retro)
- [ ] DPAI / DFU Side Drawer Performance Investigation (Incident)
- [ ] SNOP / Turkish Localisation Checklist (Checklist)
- [ ] SNOP / Supply Chain Data Model (Reference)
- [ ] Processes / Engineering On-Call Runbook (Process)
- [ ] Processes / Code Review Standards (Process)

---

---

# 🧪 TESTING CHECKLIST

---

## Functional Tests

### Auth & Roles
- [ ] Login with Admin → all pages accessible
- [ ] Login with PM → can create/edit tickets, access reports
- [ ] Login with Developer → can create tickets, log time, view own data
- [ ] Login with Viewer → read-only everywhere, no create buttons visible
- [ ] 403 returned when Developer hits admin endpoint
- [ ] JWT expiry after 24h forces re-login

### Tickets
- [ ] Create ticket via form — all fields saved correctly
- [ ] Create ticket via NL input — NOVA fills all fields, confidence scores shown
- [ ] Duplicate warning fires when similarity > 0.85
- [ ] Edit ticket inline — changes saved on blur
- [ ] Status transition follows allowed matrix (role-dependent)
- [ ] Comment thread — reply nests correctly, @mention triggers notification
- [ ] File attachment — upload, preview image, download non-image
- [ ] Activity log shows all changes with correct timestamps

### Wiki
- [ ] Create page in a space — appears in sidebar hierarchy
- [ ] TipTap editor — Markdown shortcuts work, code blocks highlight
- [ ] /ticket DPAI-123 — embeds linked ticket card in page
- [ ] Auto-save fires every 30s — "Saved" indicator updates
- [ ] Version history — restore previous version replaces content
- [ ] Cross-link from ticket → wiki page opens correct page

### NOVA AI Features
- [ ] Semantic search — "rate limiting" finds "request throttling" wiki page
- [ ] NL query — "Who fixed the pagination bug?" returns correct answer with citation
- [ ] Sprint retro generated after sprint completion
- [ ] Standup generated by 9AM for all active engineers
- [ ] Knowledge gap widget shows undocumented topics
- [ ] Burn rate alert fires at 70%, 85%, 100%
- [ ] NOVA status shows "online" when Ollama is running
- [ ] NOVA gracefully shows "AI unavailable" when Ollama is down — app still works

### Sprint & Kanban
- [ ] Create sprint with goal, dates, capacity
- [ ] Drag ticket from backlog to sprint — appears in sprint
- [ ] Drag ticket between kanban columns — status updates in DB
- [ ] Sprint complete modal — incomplete tickets moved to backlog
- [ ] Burndown chart shows ideal vs actual lines correctly
- [ ] Swimlane toggle — grouping by assignee/priority works

### Notifications
- [ ] Bell shows unread count badge
- [ ] Assigning ticket sends notification to assignee
- [ ] @mention sends notification to mentioned user
- [ ] Mark all as read clears badge

---

## Performance Tests

| Test | Target | Actual | Pass? |
|---|---|---|---|
| Dashboard initial load | < 2s | | |
| Ticket list (100 tickets) | < 500ms | | |
| Semantic search response | < 500ms | | |
| NOVA ticket analysis (async) | < 3s | | |
| NOVA standup generation | < 5s | | |
| Wiki page load | < 500ms | | |
| Kanban board (35 tickets) | Smooth drag | | |

---

## Edge Cases

- [ ] Empty sprint — burndown shows flat line, no errors
- [ ] Wiki page with no content — graceful empty state in editor
- [ ] Search with no results — "No results found, try rephrasing"
- [ ] Duplicate ticket — user can still proceed despite warning
- [ ] Invalid login — clear "Invalid email or password" message
- [ ] File > 10MB — rejected with clear error message
- [ ] Viewer accessing /admin/users — 403 with message
- [ ] Ollama down — ticket creation still works, NOVA panel shows "AI unavailable"
- [ ] 35 tickets on kanban — all render without performance issues
- [ ] Concurrent edits on same wiki page — last write wins, activity log shows both

---

---

# 🎬 DEMO DAY PLAN

**Date:** May 5–8, 2026 | **Format:** 10 min demo + 5 min Q&A

## Demo Script

| Time | Action | Feature |
|---|---|---|
| 0:00 | Login as PM → Dashboard KPIs, hours by POD, issue split donut | Role-based access, analytics |
| 1:00 | Open Kanban → drag DPAI-1018 In Progress → In Review | P0: Kanban drag-drop |
| 2:00 | Type in NL box: "Bug in DPAI forecasting grid when scrolling, high priority, assign to Anand" → NOVA fills all fields, duplicate warning shows | P0: NL creation, NOVA AI |
| 3:00 | Sprint 14 → burndown chart, velocity, checklist | P0: Sprint, P1: Analytics |
| 4:30 | Wiki → open Forecasting Module page, TipTap editor, version history | P0: Knowledge base |
| 5:30 | Cmd+K: "What was decided about API versioning?" → NOVA semantic result + citation | P0: NOVA semantic search |
| 6:30 | NL query: "Who spent the most hours on DPAI bugs this month?" → NOVA synthesises from worklogs | P0: NOVA RAG query |
| 7:30 | Complete Sprint 14 → NOVA retro generated → shows in wiki | P1: Auto documentation |
| 8:30 | Knowledge gaps: "No docs for: rate limiting, WebSocket" → create stub | P0: Gap detection |
| 9:30 | Switch to Viewer → restricted access. Show burn rate alert dashboard | P2: RBAC, Breakthrough |

> **Key demo line:** *"This is NOVA — Trackly's own built-in AI. It runs entirely on your server using Llama 3.1. No OpenAI, no external APIs, your data never leaves your machine."*

## Q&A Prep

| Question | Answer |
|---|---|
| How is search different from keyword? | 384-dim embeddings via sentence-transformers + pgvector cosine distance. "Request throttling" finds "Rate Limiting Policy" with zero keyword overlap. |
| Is the AI just a chatbot? | No. NOVA runs a multi-step agentic flow: embed → deduplicate → classify → estimate → assign. Each step is distinct reasoning by Llama 3.1. |
| Why not use ChatGPT or Claude? | We built our own — NOVA. Runs on Llama 3.1 8B via Ollama. Zero API cost, zero data leaving your server, works fully offline. |
| Can this replace Jira in production? | Analytics foundation already runs on real 3SC Jira data. ~₹10L/year licence saving, all data on-premise, no vendor lock-in. |
| Who can use this beyond engineering? | Any team — Product, QA, Finance, HR, Delivery, Sales. Client burn rate alerts serve Finance directly. Standup generator works for any team. |

---

---

# 📝 DAILY LOG

> Update every day. One row per day — what was completed, what's blocked, what's next.

| Date | Completed | Blockers | Next |
|---|---|---|---|
| Apr 7 | Architecture doc ✅ · Docker base ✅ · pgvector ✅ | — | Ticket CRUD + NOVA setup |
| Apr 8 | | | |
| Apr 9 | | | |
| **Apr 10** | **⚑ PHASE 1 DEADLINE** | | |
| Apr 11 | | | |
| Apr 12 | | | |
| Apr 13 | | | |
| Apr 14 | | | |
| Apr 15 | | | |
| Apr 16 | | | |
| **Apr 17** | **⚑ PHASE 2 DEADLINE — MVP Demo** | | |
| Apr 18 | | | |
| Apr 19 | | | |
| Apr 20 | | | |
| Apr 21 | | | |
| Apr 22 | | | |
| Apr 23 | | | |
| **Apr 24** | **⚑ PHASE 3 DEADLINE — Feature Review** | | |
| Apr 25 | | | |
| Apr 26 | | | |
| Apr 27 | | | |
| Apr 28 | | | |
| Apr 29 | | | |
| Apr 30 | | | |
| **May 1** | **⚑ FINAL SUBMISSION** | | |
| May 2 | Demo prep | | |
| May 3 | Demo rehearsal | | |
| May 4 | Final walkthrough | | |
| **May 5–8** | **⚑ DEMO DAY** | | |

---

## 🔗 Quick Links

| Resource | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| NOVA status | http://localhost:8000/api/nova/status |
| Ollama API | http://localhost:11434 |
| Mailhog (email dev) | http://localhost:8025 |
| pgAdmin (optional) | http://localhost:5050 |
| Architecture Doc | docs/TRACKLY_ARCHITECTURE.docx |
| Requirements Doc | docs/TRACKLY_REQUIREMENTS.docx |
| NOVA Setup Guide | NOVA_AI_SETUP.md |
| pgvector Docs | https://github.com/pgvector/pgvector |
| TipTap Docs | https://tiptap.dev/docs |
| dnd-kit Docs | https://dndkit.com |
| Ollama Docs | https://ollama.com/docs |
| APScheduler Docs | https://apscheduler.readthedocs.io |

---

*Last updated: April 11, 2026*
*Update status daily: ⬜ Not Started → 🔄 In Progress → ✅ Done*
*Powered by NOVA — Neural Orchestration & Velocity Assistant · Built by the Trackly team · 3SC Hackathon 2026*
