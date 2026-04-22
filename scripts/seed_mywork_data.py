"""
Seed realistic tickets, worklogs, and an active sprint for all users.
Run: python scripts/seed_mywork_data.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, timedelta
import random
import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.ticket import JiraTicket, Worklog
from app.models.sprint import Sprint

DB_URL  = os.getenv("DATABASE_URL", "postgresql://anandverma@localhost:5432/timesheet-tracker-db")
ORG_ID  = "d245532a-ef59-489f-bbba-74b8c59f86c4"

engine  = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

USERS = [
    {"name": "Aastha Rai",              "pod": "DPAI",  "prefix": "DPAI"},
    {"name": "Swapnil Akash",           "pod": "EDM",   "prefix": "EDM"},
    {"name": "Aditya Narendra Warhade", "pod": "EDM",   "prefix": "EDM"},
    {"name": "Kartik Keswani",          "pod": "SNPRM", "prefix": "SNPRM"},
    {"name": "Srinivasan Seva",         "pod": "DPAI",  "prefix": "DPAI"},
    {"name": "Vishal Raina",            "pod": "SNOP",  "prefix": "SNOP"},
    {"name": "Anoop Kumar Rai",         "pod": "PA",    "prefix": "PA"},
    {"name": "Abhishek Jain",           "pod": "PLAT",  "prefix": "PLAT"},
    {"name": "Sarfraz .",               "pod": "TMSNG", "prefix": "TMSNG"},
]

STATUSES = ["In Progress", "In Progress", "In Review", "To Do", "To Do",
            "Blocked", "In Progress", "In Review", "To Do", "Blocked"]

PRIORITIES = ["High", "High", "Medium", "Medium", "Medium", "Low", "Highest", "Medium", "Low", "High"]

ISSUE_TYPES = ["Story", "Bug", "Task", "Story", "Bug", "Task", "Story", "Bug", "Task", "Story"]

CLIENTS = ["Colgate", "Nestle", "Unilever", "3SC Internal", "Procter & Gamble",
           "Colgate", "Nestle", "3SC Internal", "Unilever", "Procter & Gamble"]

TICKET_SUMMARIES = [
    "Implement authentication flow for {pod} module",
    "Fix data sync issue in {pod} pipeline",
    "Add pagination to {pod} list view",
    "Refactor {pod} service layer for performance",
    "Write unit tests for {pod} API endpoints",
    "Integrate {pod} with notification service",
    "Debug memory leak in {pod} background job",
    "Update {pod} dashboard UI components",
    "Migrate {pod} schema to v2 format",
    "Add retry logic to {pod} external API calls",
    "Fix broken search in {pod} module",
    "Implement bulk export feature for {pod}",
    "Optimise slow query in {pod} reports",
    "Add audit logging to {pod} user actions",
    "Resolve {pod} CORS issue on staging",
]

today = date.today()

def gen_uuid():
    return str(uuid.uuid4())

def seed():
    db = Session()

    # ── Active sprint ─────────────────────────────────────────────────────────
    active_sprint = db.query(Sprint).filter(
        Sprint.org_id == ORG_ID,
        Sprint.status == "active",
    ).first()

    if not active_sprint:
        active_sprint = Sprint(
            id         = gen_uuid(),
            org_id     = ORG_ID,
            name       = "Sprint 4",
            goal       = "Deliver core feature set for Q2",
            start_date = today - timedelta(days=5),
            end_date   = today + timedelta(days=9),
            status     = "active",
        )
        db.add(active_sprint)
        db.flush()
        print(f"Created active sprint: {active_sprint.name} (ends {active_sprint.end_date})")
    else:
        print(f"Using existing active sprint: {active_sprint.name}")

    sprint_id = active_sprint.id
    created_tickets = 0
    created_logs    = 0

    for user in USERS:
        name   = user["name"]
        pod    = user["pod"]
        prefix = user["prefix"]

        # Check existing tickets for this user
        existing_keys = {
            t.jira_key for t in db.query(JiraTicket.jira_key).filter(
                JiraTicket.org_id   == ORG_ID,
                JiraTicket.assignee == name,
            ).all()
        }

        tickets_to_create = []
        for i in range(15):
            key = f"{prefix}-S4-{abs(hash(name)) % 1000 + i * 7}"
            if key in existing_keys:
                continue

            status     = STATUSES[i % len(STATUSES)]
            priority   = PRIORITIES[i % len(PRIORITIES)]
            issue_type = ISSUE_TYPES[i % len(ISSUE_TYPES)]
            client     = CLIENTS[i % len(CLIENTS)]
            summary    = TICKET_SUMMARIES[i % len(TICKET_SUMMARIES)].format(pod=pod)
            sp         = random.choice([1, 2, 3, 3, 5, 5, 8])
            est_hours  = sp * 2.0
            spent      = round(random.uniform(0, est_hours * 1.2), 1) if status != "To Do" else 0
            remaining  = max(0, round(est_hours - spent, 1))

            # Due dates: some overdue, some upcoming, some none
            if i % 5 == 0:
                due = today - timedelta(days=random.randint(1, 4))   # overdue
            elif i % 5 == 1:
                due = today + timedelta(days=random.randint(1, 5))   # due soon
            elif i % 5 == 2:
                due = active_sprint.end_date                          # sprint end
            else:
                due = None

            # Link first 5 tickets to active sprint
            s_id = sprint_id if i < 5 else None

            t = JiraTicket(
                id                       = gen_uuid(),
                org_id                   = ORG_ID,
                jira_key                 = key,
                project_key              = prefix,
                project_name             = f"{pod} Project",
                summary                  = summary,
                assignee                 = name,
                assignee_email           = f"{name.lower().replace(' ', '.').replace('..', '.')}@3scsolution.com",
                status                   = status,
                priority                 = priority,
                issue_type               = issue_type,
                story_points             = sp,
                hours_spent              = spent,
                original_estimate_hours  = est_hours,
                remaining_estimate_hours = remaining,
                client                   = client,
                pod                      = pod,
                sprint_id                = s_id,
                jira_created             = today - timedelta(days=random.randint(5, 30)),
                jira_updated             = today - timedelta(days=random.randint(0, 3)),
                due_date                 = due,
                url                      = f"https://jira.example.com/browse/{key}",
                is_deleted               = False,
            )
            tickets_to_create.append(t)

        db.add_all(tickets_to_create)
        db.flush()
        created_tickets += len(tickets_to_create)

        # ── Worklogs — last 14 business days ─────────────────────────────────
        work_tickets = [t for t in tickets_to_create if t.status != "To Do"]
        biz_days = []
        d = today
        while len(biz_days) < 14:
            if d.weekday() < 5:
                biz_days.append(d)
            d -= timedelta(days=1)

        for log_date in biz_days:
            # 1-2 worklogs per day on active tickets
            daily_tickets = random.sample(work_tickets, min(2, len(work_tickets)))
            for wt in daily_tickets:
                hours = round(random.uniform(1.0, 4.0), 1)
                wl = Worklog(
                    id           = gen_uuid(),
                    ticket_id    = wt.id,
                    author       = name,
                    author_email = wt.assignee_email,
                    log_date     = log_date,
                    hours        = hours,
                    comment      = f"Working on {wt.jira_key}",
                )
                db.add(wl)
                created_logs += 1

        print(f"  {name}: {len(tickets_to_create)} tickets, worklogs added")

    db.commit()
    db.close()
    print(f"\nDone — {created_tickets} tickets, {created_logs} worklogs seeded.")

if __name__ == "__main__":
    seed()
