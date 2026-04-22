"""
app/services/health_service.py — Unified pod health computation.

Single source of truth for health scoring used by:
  - GET /api/spaces/{pod}/health       (detail radar)
  - GET /api/analytics/pod-summary     (card-level health_score)

All 7 radar dimensions and the rolled-up health_score come from here
so the Spaces list cards and the SummaryTab always show the same number.
"""

from __future__ import annotations

from datetime import date
from typing import Optional


# ── Status normalisation (mirrors spaces.py helpers) ────────────────────────

_DONE     = {"done", "closed", "resolved", "won't fix", "duplicate", "cancelled", "rejected"}
_BLOCKED  = {"blocked"}
_PROGRESS = {"in progress", "in development", "development ready"}
_REVIEW   = {"in review", "qa", "testing"}


def _norm(status: Optional[str]) -> str:
    s = (status or "").lower().strip()
    if s in _DONE:     return "done"
    if s in _BLOCKED:  return "blocked"
    if s in _PROGRESS: return "in_progress"
    if any(k in s for k in _REVIEW): return "in_review"
    return "todo"


# ── Core computation ─────────────────────────────────────────────────────────

def compute_health(
    tickets: list,
    active_sprint=None,
) -> dict:
    """
    Compute unified health result for a pod.

    Args:
        tickets:       list of JiraTicket ORM objects for this pod (non-deleted)
        active_sprint: Sprint ORM object or None

    Returns dict with:
        health_score   int  0-100  (average of 7 radar dims)
        radar          dict       {delivery, velocity, clarity, momentum, flow, quality, on_time}
        delivery_confidence int   0-100  (sprint-pace based, falls back to done_rate)
        trend          list[int]  7-element sparkline (recent done tickets by day)
        risk_flags     dict       {blocked, overdue, bug_rate, stale}
        sprint_prediction int     0-95 (sprint completion likelihood)
    """
    today = date.today()
    total = len(tickets) or 1  # avoid /0

    # ── Count ticket states ───────────────────────────────────────────────────
    n_done      = 0
    n_blocked   = 0
    n_overdue   = 0
    n_bugs      = 0
    n_recent    = 0  # updated in last 7 days
    n_described = 0  # has description + story_points

    for t in tickets:
        norm = _norm(t.status)
        if norm == "done":
            n_done += 1
        if norm == "blocked":
            n_blocked += 1

        if t.due_date and norm not in ("done",):
            due = t.due_date.date() if hasattr(t.due_date, "date") else t.due_date
            if due < today:
                n_overdue += 1

        itype = (t.issue_type or "").lower()
        if "bug" in itype or "defect" in itype:
            n_bugs += 1

        updated = t.jira_updated.date() if hasattr(t.jira_updated, "date") else t.jira_updated
        if updated and (today - updated).days <= 7:
            n_recent += 1

        if t.description and (t.story_points or 0) > 0:
            n_described += 1

    done_rate    = n_done    / total
    blocker_rate = n_blocked / total
    overdue_rate = n_overdue / total
    bug_rate     = n_bugs    / total
    activity     = n_recent  / total
    clarity_rate = n_described / total

    # ── Sprint velocity score ─────────────────────────────────────────────────
    sprint_prediction = None
    velocity_score    = done_rate  # fallback when no sprint

    if active_sprint:
        sp_tickets  = [t for t in tickets if getattr(t, "sprint_id", None) == active_sprint.id]
        committed   = sum(t.story_points or 0 for t in sp_tickets)
        done_pts    = sum(t.story_points or 0 for t in sp_tickets if _norm(t.status) == "done")
        remaining   = committed - done_pts

        if committed > 0:
            velocity_score = done_pts / committed

        # Sprint pace → completion prediction
        if active_sprint.start_date and active_sprint.end_date:
            total_days  = max(1, (active_sprint.end_date - active_sprint.start_date).days)
            days_left   = max(0, (active_sprint.end_date - today).days)
            elapsed     = max(1, total_days - days_left)
            pace        = done_pts / elapsed
            needed      = remaining / days_left if days_left > 0 else 0
            if needed > 0:
                sprint_prediction = min(95, int(pace / needed * 100))
            else:
                sprint_prediction = 95  # sprint done or no remaining

    # ── 7 Radar dimensions (0–100 each) ──────────────────────────────────────
    radar = {
        "delivery":  round(done_rate * 100),
        "velocity":  round(velocity_score * 100),
        "clarity":   round(clarity_rate * 100),             # tickets with description+SP
        "momentum":  round(activity * 100),                  # recently active tickets
        "flow":      round(max(0, (1 - blocker_rate * 3)) * 100),   # penalise blockers harder
        "quality":   round(max(0, (1 - bug_rate * 2)) * 100),       # penalise bugs
        "on_time":   round(max(0, (1 - overdue_rate * 2)) * 100),   # penalise overdue
    }
    # Clamp all to 0–100
    radar = {k: max(0, min(100, v)) for k, v in radar.items()}

    health_score = round(sum(radar.values()) / 7)

    # ── Delivery confidence (for pod card pill) ───────────────────────────────
    # Blends health_score with sprint prediction if available
    if sprint_prediction is not None:
        delivery_confidence = round(health_score * 0.5 + sprint_prediction * 0.5)
    else:
        delivery_confidence = health_score

    # ── 7-day activity sparkline ──────────────────────────────────────────────
    trend = _build_trend(tickets, today)

    # ── Risk flags ────────────────────────────────────────────────────────────
    risk_flags = {
        "blocked":  n_blocked,
        "overdue":  n_overdue,
        "bug_rate": round(bug_rate * 100, 1),
        "stale":    sum(
            1 for t in tickets
            if t.jira_updated and (
                today - (t.jira_updated.date() if hasattr(t.jira_updated, "date") else t.jira_updated)
            ).days > 14
            and _norm(t.status) not in ("done",)
        ),
    }

    return {
        "health_score":         health_score,
        "radar":                radar,
        "delivery_confidence":  delivery_confidence,
        "sprint_prediction":    sprint_prediction,
        "trend":                trend,
        "risk_flags":           risk_flags,
    }


def _build_trend(tickets: list, today: date) -> list[int]:
    """Count done tickets per day for the last 7 days (Mon→Sun order)."""
    from datetime import timedelta
    counts = {}
    for i in range(7):
        d = today - timedelta(days=6 - i)
        counts[d] = 0

    for t in tickets:
        if _norm(t.status) == "done" and t.jira_updated:
            d = t.jira_updated.date() if hasattr(t.jira_updated, "date") else t.jira_updated
            if d in counts:
                counts[d] += 1

    return list(counts.values())


# ── Anomaly detection (rule-based, no LLM needed) ────────────────────────────

ANOMALY_RULES = [
    # (condition_fn, type, severity, description_template)
    (
        lambda h: h["risk_flags"]["blocked"] >= 3,
        "high_blockers",
        "high",
        lambda h: f"{h['risk_flags']['blocked']} blocked tickets — delivery at risk",
    ),
    (
        lambda h: h["radar"]["velocity"] < 30,
        "low_velocity",
        "high",
        lambda h: f"Velocity score {h['radar']['velocity']}% — sprint completion unlikely",
    ),
    (
        lambda h: h["risk_flags"]["overdue"] >= 2,
        "overdue_spike",
        "medium",
        lambda h: f"{h['risk_flags']['overdue']} overdue tickets — SLA pressure",
    ),
    (
        lambda h: h["radar"]["quality"] < 50,
        "quality_risk",
        "medium",
        lambda h: f"Bug rate elevated — quality score {h['radar']['quality']}%",
    ),
    (
        lambda h: h["radar"]["momentum"] < 25,
        "stalled",
        "medium",
        lambda h: f"Low activity — only {h['radar']['momentum']}% tickets updated this week",
    ),
    (
        lambda h: (h["sprint_prediction"] or 100) < 50,
        "sprint_at_risk",
        "high",
        lambda h: f"Sprint completion predicted at {h['sprint_prediction']}%",
    ),
]


def detect_anomalies(pod: str, health_result: dict) -> list[dict]:
    """Return list of anomaly dicts for a pod given its health result."""
    from datetime import datetime
    anomalies = []
    for condition, atype, severity, description_fn in ANOMALY_RULES:
        try:
            if condition(health_result):
                anomalies.append({
                    "pod":         pod,
                    "type":        atype,
                    "severity":    severity,
                    "description": description_fn(health_result),
                    "detected_at": datetime.utcnow().isoformat(),
                })
        except Exception:
            pass
    return anomalies
