# Analytics and My Team Pages: Data Logic and Workflow

This document explains what data is shown on the Trackly Analytics page and My Team page, which backend endpoints provide that data, and how each value is calculated.

## Common Data Rules

- All backend queries are scoped to the logged-in user's `org_id`.
- Deleted Jira tickets are excluded with `jira_tickets.is_deleted = false`.
- Most ticket metrics come from `jira_tickets`.
- Time-based hour metrics come from `worklogs` and, in the My Team summary, also from `manual_entries`.
- Done tickets are normally identified by status `Done`, `Closed`, or `Resolved`.
- AI text is generated through NOVA/EOS where available. If the AI call fails, several endpoints return a deterministic fallback summary.

---

## Analytics Page

Frontend page: `src/features/analytics/AnalyticsPage.tsx`

The Analytics page is a leadership view for workload, delivery risk, bug cost, client health, knowledge gaps, resource planning, and benchmark comparisons.

### 1. Workload Distribution

Endpoint: `GET /api/analytics/workload`

Displayed data:

- Engineer name
- POD
- Total hours for the current month

Workflow:

1. The backend joins `worklogs` with `jira_tickets`.
2. It filters tickets to the current organisation and excludes deleted tickets.
3. It filters worklogs to the selected month/year. If no month/year is passed, it uses the current month and current year.
4. It groups rows by ticket assignee and ticket POD.
5. It sums `worklogs.hours`.

Calculation:

```text
total_hours = sum(worklog.hours)
grouped by assignee + pod
for the selected month/year
```

Frontend behavior:

- The page sorts engineers by `total_hours` descending.
- Only the top 20 rows are shown in the workload bar chart.

### 2. Team Health Monitor

Source data: same response as `GET /api/analytics/workload`

Displayed data:

- Engineer
- Current-month hours
- Health/risk badge: Healthy, Watch, or High Risk
- Workload bar

Workflow:

1. The frontend calculates the average hours across the workload rows.
2. Each engineer's hours are compared against fixed thresholds.
3. The UI marks high-hour engineers as potential burnout risk.

Calculations:

```text
avg_hours = sum(total_hours for all workload rows) / number_of_rows
ratio = engineer_total_hours / max(1, avg_hours)

burnoutRisk =
  High   if total_hours > 50
  Medium if total_hours > 40
  Low    otherwise

overloaded = ratio > 1.4

bar_width_percent = min(100, total_hours / 60 * 100)
```

Notes:

- The risk badge is based on hours, not sentiment or ticket status.
- `overloaded` only affects row highlighting.
- If any engineer is `High Risk`, EOS displays a recommendation to redistribute work or reduce sprint scope.

### 3. Velocity Anomaly Detection

Endpoint: `GET /api/analytics/velocity`

Displayed data:

- Completed sprint trend
- Velocity drops of 20% or more
- Committed points, completed points, and shortfall

Backend workflow:

1. The backend loads the last 10 completed sprints for the organisation.
2. Only sprints with non-null `velocity` are included.
3. Sprints are ordered by end date descending in the query, then reversed before returning so the frontend receives chronological trend data.

Backend calculation:

```text
points_completed = sprint.velocity
```

Frontend normalization:

```text
completed = row.completed or row.points_completed or row.velocity or 0
committed =
  row.committed
  or row.points_committed
  or completed + max(3, round(completed * 0.2))
```

Anomaly calculation:

```text
change = (current_completed - previous_completed) / previous_completed

anomaly exists when change <= -0.20
dropPct = abs(change)
shortfall = committed - completed
```

Notes:

- The backend currently returns completed points only.
- If committed points are not returned, the frontend estimates committed points as completed points plus roughly 20%, with a minimum uplift of 3 points.

### 4. Emotion-Aware Work Management

Endpoint: `GET /api/analytics/sentiment-signals`

Displayed data:

- Engineer
- Emotional signal: Frustration, Overload, or Disengagement
- Severity: medium or high
- Trigger phrases
- Related ticket keys
- Sprint label

Workflow:

1. The backend loads up to 200 non-deleted ticket comments from the last 72 hours.
2. Comments are joined to tickets and authors.
3. Comments are grouped by author.
4. If NOVA is available, the backend asks it to identify emotional signals from recent comments.
5. If NOVA is unavailable or returns no usable output, the backend uses keyword matching.
6. Results are sorted so high-severity signals appear first.

Keyword fallback logic:

```text
Frustration keywords:
breaking, again, keeps, same issue, keeps failing, still broken,
why is this, ridiculous

Overload keywords:
too many, overwhelmed, not enough time, too much,
can't keep up, behind on, swamped

Disengagement keywords:
not sure why, don't understand, what's the point, unclear, no context
```

Severity calculation:

```text
best_score = number of matched phrases in strongest category

severity =
  high   if best_score >= 2
  medium otherwise
```

Notes:

- This feature analyzes work comments for care signals; it does not inspect private messages.
- The window is fixed at 72 hours.

### 5. Real Cost of a Bug

Endpoint: `GET /api/analytics/bug-cost`

Displayed data:

- Total bug count
- Open bug count
- High-priority bug count
- Total bug hours
- Estimated cost
- Average hours per bug
- Bug cost by POD

Workflow:

1. The backend loads all non-deleted tickets where `issue_type = "Bug"`.
2. It sums `hours_spent` from those bug tickets.
3. It uses a fixed placeholder rate of `$75/hour`.
4. It groups bug counts and hours by POD.

Calculations:

```text
total_bugs = count(bug tickets)
open_bugs = count(bug tickets where status is not Done/Closed/Resolved)
high_priority_bugs = count(bug tickets where priority is High or Highest)
total_hours = sum(ticket.hours_spent)
total_cost_usd = total_hours * 75
avg_hours_per_bug = total_hours / max(1, total_bugs)

pod_cost_usd = pod_bug_hours * 75
```

Notes:

- The hourly rate is currently a hardcoded placeholder.
- Bug hours come from `jira_tickets.hours_spent`, not from worklog rows.

### 6. Recurring Problem Detector

Endpoint: `GET /api/analytics/recurring-problems`

Displayed data:

- Recurring keyword pattern
- Number of occurrences
- Up to 5 example ticket keys
- Severity

Workflow:

1. The backend loads all non-deleted bug tickets.
2. It extracts lowercase words of at least 4 letters from each bug summary.
3. Common stop words and generic bug words are ignored.
4. A keyword becomes a recurring pattern if it appears in at least 3 bug tickets.
5. The top 10 patterns are returned by occurrence count.

Severity calculation:

```text
severity =
  high   if occurrences >= 6
  medium if occurrences >= 4
  low    if occurrences >= 3
```

### 7. Client Health Score

Endpoint: `GET /api/analytics/client-health`

Displayed data:

- Client name
- Health score
- Status: Healthy, At Risk, or Critical
- Ticket count
- Delivered percentage
- Bug percentage
- Blocked tickets
- Overdue tickets
- Total hours

Workflow:

1. The backend loads all non-deleted tickets with a non-empty `client`.
2. It groups tickets by client.
3. For each client it counts total, done, blocked, bug, overdue, and hours.
4. It calculates rates and combines them into a health score.

Calculations:

```text
delivery_rate = done_tickets / total_tickets * 100
bug_rate = bug_tickets / total_tickets * 100
block_rate = blocked_tickets / total_tickets * 100
overdue_rate = overdue_tickets / total_tickets * 100

health_score =
  delivery_rate
  - bug_rate * 0.5
  - block_rate * 1.5
  - overdue_rate * 2.0

health_score is clamped to 0-100
```

Status:

```text
Healthy  if health_score >= 70
At Risk  if health_score >= 40
Critical otherwise
```

Notes:

- A ticket is overdue when `due_date` is before today and the ticket is not done.
- A ticket is blocked when the status text contains `block`.

### 8. Knowledge Gaps

Endpoints:

- `GET /api/nova/knowledge-gaps`
- `POST /api/nova/knowledge-gaps/detect`
- `POST /api/wiki/pages` when creating a stub or generated article

Displayed data:

- Topic
- Suggestion
- Related ticket count
- Wiki coverage percentage
- Detection date

Workflow:

1. The page loads existing knowledge gaps from NOVA.
2. The user can run detection, which asks the backend to detect missing documentation topics from ticket/wiki context.
3. The user can create a stub page in the first available wiki space.
4. The user can ask EOS to generate a full article based on the detected gap.

Displayed fields:

```text
topic = detected missing knowledge topic
ticket_count = number of tickets related to that missing topic
wiki_coverage = estimated documentation coverage percentage
suggestion = recommended documentation/action
detected_at = timestamp when the gap was found
```

### 9. Predictive Resource Planning

Endpoint: `GET /api/analytics/resource-gaps`

Displayed data:

- Skill or role needed
- Goal that needs the skill
- Urgency: Hire Now or Plan Ahead
- Needed-by timing
- Explanation note
- Forecast note

Workflow:

1. The backend loads all active users in the organisation.
2. It loads up to 50 open high-priority tickets.
3. High-priority means priority is `High`, `Highest`, or `Critical`.
4. Done, closed, and resolved tickets are excluded.
5. The backend asks NOVA to identify skill or hiring gaps from team composition and ticket pressure.
6. If NOVA is unavailable, a rule-based fallback is used.

Rule-based fallback:

```text
For the top 3 pods by high-priority open ticket count:
  if high_priority_count > 5 and active_pod_members < 3:
    create a resource gap

urgency =
  high   if high_priority_count > 8
  medium otherwise
```

Forecast note:

```text
EOS forecasts {gap_count} skill gap(s)
based on {high_priority_ticket_count} high-priority open tickets
across your {active_team_size}-person team.
```

### 10. Cross-Organizational Pattern Learning

Endpoint: `GET /api/analytics/benchmarks`

Displayed data:

- Sprint predictability
- Average ticket resolution time
- Knowledge coverage
- Industry average
- Similar-team benchmark
- Insight

Workflow and calculations:

#### Sprint Predictability

1. The backend loads up to 20 completed sprints with non-null velocity.
2. It calculates the average velocity.
3. A sprint is predictable if its velocity is within 20% of that average.

```text
avg_velocity = sum(velocity) / number_of_sprints
predictable_sprint = abs(sprint_velocity - avg_velocity) / avg_velocity <= 0.20
predictability = predictable_sprints / total_sprints * 100
```

#### Average Ticket Resolution Time

1. The backend loads up to 500 resolved tickets.
2. It uses `jira_created` and `jira_updated`.
3. It averages the day difference.

```text
resolution_days = jira_updated - jira_created
avg_resolution_days = sum(resolution_days) / resolved_ticket_count
```

#### Knowledge Coverage

1. The backend loads all `KnowledgeGap` rows for the organisation.
2. It averages their `wiki_coverage` value.

```text
avg_wiki_coverage = sum(gap.wiki_coverage) / number_of_gaps
```

Static comparison values:

```text
Sprint predictability:
  industry_avg = 68%
  similar_teams = 79%

Avg ticket resolution time:
  industry_avg = 4.1d
  similar_teams = 2.8d

Knowledge coverage:
  industry_avg = 48%
  similar_teams = 71%
```

---

## My Team Page

Frontend page: `src/features/team/TeamPage.tsx`

The My Team page is a people-management view. It shows the logged-in user's reporting hierarchy, work summary for the selected date range, AI team brief, institutional memory, cognitive load, team chemistry, and member cards.

### 1. Team Member List / Reporting Hierarchy

Endpoint: `GET /api/users/members`

Displayed data:

- Member ID
- Name
- Email
- Role
- POD
- Employee number
- Reporting manager reference
- Title

Backend workflow:

1. The backend loads all active users in the current organisation.
2. It orders them by name.
3. It returns lightweight member profile fields.

Frontend hierarchy logic:

```text
if current_user.role == "admin":
  myTeam = all active org members except finance_viewer
else:
  myProfile = org member whose email matches current_user.email
  myIds = [myProfile.emp_no, myProfile.id, myProfile.email, myProfile.name]
  myTeam = members where member.reporting_to is in myIds
           and member.role != "finance_viewer"
```

Notes:

- `reporting_to` supports multiple reference styles: employee number, user ID, email, or name.
- Finance viewers are excluded from the people-management team list.

### 2. Date-Range Work Summary

Endpoint: `GET /api/summary`

Used for:

- Total Hours stat
- Tickets stat
- Active count
- Idle count
- Each member card's hours, tickets, and client list
- EOS Team Brief prompt

Backend workflow:

1. Worklog hours are loaded from `worklogs` joined to `jira_tickets`.
2. Manual hours are loaded from `manual_entries` joined to `users`.
3. Both sources are filtered by organisation and selected date range.
4. Optional filters for user, POD, client, and project are applied.
5. Ticket counts are loaded from `jira_tickets`.
6. Ticket counts are not date-filtered; they represent matching current tickets.
7. The endpoint aggregates by user, client, POD, and issue type.

Per-user calculations:

```text
user_hours =
  sum(worklog.hours where worklog.author = user)
  + sum(manual_entry.hours where manual_entry.user_id = user.id)

user_tickets =
  count(jira_tickets where jira_tickets.assignee = user)

user_clients =
  unique clients from that user's worklogs and manual entries
```

Team-level calculations on the frontend:

```text
teamWithStats = myTeam joined with summary.by_user by member.name

totalHours = sum(member.summary.hours)
totalTickets = sum(member.summary.tickets)
activeCount = count(members where hours >= 25)
idleCount = count(members where hours == 0)
```

Notes:

- If a direct report has no summary row, the frontend shows them with `0h`, `0 tickets`, and no clients.
- The date range comes from the global filter store.
- Ticket counts are current assignment counts, not only tickets created or updated inside the date range.

### 3. Team Search

Source data: frontend-only filtering of `teamWithStats`

Search matches:

- Member name
- Member title
- Member POD

Logic:

```text
query = lowercase(search_text)
show member if:
  name contains query
  or title contains query
  or pod contains query
```

### 4. Team Stats Strip

Displayed stats:

- Members
- Total Hours
- Tickets
- Active
- Idle

Calculations:

```text
Members = myTeam.length
Total Hours = round(sum(summary.hours for all team members))
Tickets = sum(summary.tickets for all team members)
Active = count(team members with hours >= 25)
Idle = count(team members with hours == 0)
```

### 5. EOS Team Brief

Source endpoints:

- `GET /api/summary`
- `POST /api/nova/query`

Displayed data:

- A short AI-generated leadership brief

Workflow:

1. The page waits until filtered team data exists.
2. It builds a prompt containing the selected date range, each team member's hours and tickets, total team hours, total tickets, active count, and idle count.
3. It asks EOS/NOVA for a 3-sentence leadership brief.
4. The brief is generated once automatically after team data loads.

Prompt inputs:

```text
member_lines = "- {name}: {hours}h, {tickets} tickets"
total_team_hours
total_tickets
active_members_25h_plus
idle_members_0h
date_range
```

Requested AI output:

```text
1. Overall team health
2. Who needs attention
3. One actionable recommendation
```

### 6. Institutional Memory Map

Endpoint: `GET /api/nova/memory-graph`

Displayed data:

- EOS summary
- Bus-factor risk banner for high-risk PODs
- Top experts by ticket count
- Expert POD tags
- Ticket count per expert

Backend workflow:

1. The backend loads all non-deleted tickets with an assignee.
2. It groups tickets by assignee.
3. For each assignee, it tracks unique PODs, issue types, and ticket count.
4. It also tracks unique contributors per POD.
5. It marks PODs with one or two contributors as bus-factor risks.
6. It asks EOS/NOVA for a short institutional-knowledge summary.

Calculations:

```text
ticket_count = count(tickets assigned to member)
pods = unique ticket.pod values for member
specializations = unique ticket.issue_type values for member
knowledge_breadth = count(unique pods)

pod_contributors = unique assignees in each pod

bus_factor_risk =
  High   if contributors == 1
  Medium if contributors == 2
  Low    otherwise
```

Frontend behavior:

- Shows up to 6 experts from the returned expertise map.
- Shows a bus-factor warning when any returned POD has `risk = "High"`.

### 7. Cognitive Load Score

Endpoint: `GET /api/nova/cognitive-load`

Displayed data:

- Member name
- Load score
- Level: Overloaded, High, Moderate, or Optimal
- WIP ticket count
- Overdue ticket count
- AI summary

Backend workflow:

1. The backend loads all non-deleted tickets with an assignee.
2. Done, closed, and resolved tickets are excluded.
3. It groups open tickets by assignee.
4. It counts WIP tickets, high-priority tickets, overdue tickets, and story points.
5. It calculates a score from those counts.
6. It asks EOS/NOVA to summarize the load distribution.

Calculation:

```text
raw_score =
  wip_count * 10
  + high_priority_count * 15
  + overdue_count * 20

load_score = min(100, raw_score)
```

Level:

```text
Overloaded if load_score >= 70
High       if load_score >= 50
Moderate   if load_score >= 30
Optimal    otherwise
```

Notes:

- High priority means `High` or `Highest`.
- Overdue means `due_date < today`.
- Story points are returned for context but are not part of the current load score formula.

### 8. Team Chemistry Analyser

Endpoint: `GET /api/nova/team-chemistry`

Displayed data:

- POD
- Number of contributing members
- Average story points
- Imbalance percentage
- Most loaded member
- Least loaded member
- AI analysis

Backend workflow:

1. The backend loads all non-deleted tickets that have both an assignee and a POD.
2. It groups tickets by POD and then by assignee.
3. It sums story points for each assignee inside each POD.
4. It only analyzes PODs with at least 2 contributing members.
5. It calculates workload imbalance using coefficient of variation.
6. It asks EOS/NOVA for collaboration analysis and a recommendation.

Calculations:

```text
member_points = sum(ticket.story_points for each member in a pod)
avg_pts = sum(member_points) / member_count
std_dev = sqrt(sum((member_points - avg_pts)^2) / member_count)
imbalance_pct = round(std_dev / max(avg_pts, 1) * 100)

most_loaded = member with highest member_points
least_loaded = member with lowest member_points
```

Frontend color logic:

```text
red   if imbalance_pct >= 60
amber if imbalance_pct >= 35
green otherwise
```

### 9. Team Member Cards

Sources:

- Member profile from `GET /api/users/members`
- Work summary from `GET /api/summary`

Displayed data:

- Avatar initials
- Name
- Title or role
- Status badge
- Hours
- Tickets
- POD and other profile metadata

Workflow:

1. The frontend builds `teamWithStats` by matching each direct report to `summary.by_user` using `member.name`.
2. Missing summary rows become zero-value summaries.
3. The card renders profile data from `/users/members` and activity data from `/summary`.

Main calculations:

```text
member_hours = summary.by_user[member.name].hours or 0
member_tickets = summary.by_user[member.name].tickets or 0
member_clients = summary.by_user[member.name].clients or []
```

Status badge:

- The status badge is calculated on the frontend from member hours.
- Exact labels depend on the `getStatus(hours)` helper in `TeamPage.tsx`.
- The page-level stats define active members as `hours >= 25` and idle members as `hours == 0`.

### 10. Member Detail Drawer / Activity

Related endpoint: `GET /api/activity`

The Team page imports `fetchUserActivity`, which calls `/activity` with:

```text
user
date_from
date_to
```

Expected activity fields:

```text
source = ticket or manual
date
activity
hours
pod
client
entry_type
ticket_key
ticket_summary
notes
user_name
```

This supports detailed timesheet/activity views for a selected team member.

---

## Quick Endpoint Map

Analytics page:

```text
GET  /api/analytics/workload
GET  /api/analytics/velocity
GET  /api/analytics/bug-cost
GET  /api/analytics/recurring-problems
GET  /api/analytics/client-health
GET  /api/analytics/sentiment-signals
GET  /api/analytics/benchmarks
GET  /api/analytics/resource-gaps
GET  /api/nova/knowledge-gaps
POST /api/nova/knowledge-gaps/detect
POST /api/wiki/pages
```

My Team page:

```text
GET  /api/users/members
GET  /api/summary
POST /api/nova/query
GET  /api/nova/memory-graph
GET  /api/nova/cognitive-load
GET  /api/nova/team-chemistry
GET  /api/activity
```

