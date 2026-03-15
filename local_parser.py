"""
local_parser.py — Accurate natural language time entry parser.

Handles inputs like:
  "Sprint planning 2h DPAI Colgate, then 4x 30min 1:1s"
  "On Mar 13, 4h worked on DPAI Budget grid"
  "Monday: standup 15min, code review 2h DevOps, team meeting 1h Jockey"
  "Yesterday had stakeholder call 1.5h, reviewed 3 PRs 2h"
  "This week: 8h sprint ceremonies DPAI, 6h 1:1s, 3h interviews"
"""

import re
from datetime import date, timedelta
from dateutil.parser import parse as dateutil_parse
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
from collections import defaultdict
from typing import Optional


# ── Constants ──────────────────────────────────────────────────────────────────

ENTRY_TYPES = ["Meeting", "Bugs", "Feature", "Program Management"]

TYPE_KEYWORDS: dict[str, list[str]] = {
    "Meeting":             ["meeting", "standup", "stand-up", "stand up", "sync",
                            "call", "ceremony", "retrospective", "retro", "demo",
                            "stakeholder", "town hall", "all hands", "all-hands",
                            "1:1", "1-1", "one on one", "one-on-one", "check-in",
                            "catch up", "interview", "hiring", "screening"],
    "Bugs":                ["bug", "bugfix", "fix", "defect", "issue", "error",
                            "patch", "hotfix", "regression", "incident"],
    "Feature":             ["feature", "develop", "implement", "build", "create",
                            "task", "story", "epic", "sprint", "coding", "code",
                            "design", "review", "pr review", "code review",
                            "pull request", "testing", "qa", "deployment", "deploy",
                            "release", "refactor", "integration", "api"],
    "Program Management":  ["planning", "grooming", "refinement", "backlog",
                            "roadmap", "report", "reporting", "metrics", "update",
                            "presentation", "deck", "analysis", "kickoff",
                            "training", "workshop", "onboarding", "documentation"],
}

DAY_MAP = {
    "monday": MO(-1), "tuesday": TU(-1), "wednesday": WE(-1),
    "thursday": TH(-1), "friday": FR(-1), "saturday": SA(-1), "sunday": SU(-1),
    "mon": MO(-1), "tue": TU(-1), "wed": WE(-1), "thu": TH(-1),
    "fri": FR(-1), "sat": SA(-1), "sun": SU(-1),
}

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}


# ── Date parsing ───────────────────────────────────────────────────────────────

def resolve_date(token: str, today: date) -> Optional[date]:
    """
    Resolve a date expression to a concrete date.
    Returns None if not recognized.
    """
    t = token.lower().strip().rstrip(":")

    if t in ("today",):
        return today
    if t in ("yesterday",):
        return today - timedelta(days=1)
    if t in ("day before yesterday",):
        return today - timedelta(days=2)

    # "last monday", "this friday"
    m = re.match(r"(last|this)\s+(\w+)", t)
    if m:
        modifier, day_name = m.group(1), m.group(2)
        if day_name in DAY_MAP:
            rel = DAY_MAP[day_name]
            if modifier == "last":
                # force previous week
                d = today + relativedelta(weekday=rel)
                if d >= today:
                    d -= timedelta(weeks=1)
            else:
                d = today + relativedelta(weekday=rel)
                if d > today:
                    d -= timedelta(weeks=1)
            return d

    # plain day name "monday" → most recent past occurrence
    if t in DAY_MAP:
        d = today + relativedelta(weekday=DAY_MAP[t])
        if d >= today:
            d -= timedelta(weeks=1)
        return d

    # "Mar 13", "March 13", "Mar 13 2026", "13 Mar"
    m = re.match(r"(?:on\s+)?([a-z]+)\s+(\d{1,2})(?:[,\s]+(\d{4}))?$", t)
    if m:
        month_str, day_str, year_str = m.groups()
        month = MONTH_MAP.get(month_str[:3])
        if month:
            day  = int(day_str)
            year = int(year_str) if year_str else today.year
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # "13 Mar", "13 March"
    m = re.match(r"(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?$", t)
    if m:
        day_str, month_str, year_str = m.groups()
        month = MONTH_MAP.get(month_str[:3])
        if month:
            day  = int(day_str)
            year = int(year_str) if year_str else today.year
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # ISO "2026-03-13"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    return None


# ── Hours parsing ──────────────────────────────────────────────────────────────

def parse_hours(text: str) -> Optional[float]:
    """
    Extract hours from a string.
    Handles: 2h, 2hr, 2hrs, 2 hours, 1.5h, 30min, 30mins,
             4x30min (multiply), 2h30min (add), half hour, quarter hour
    """
    t = text.lower()

    # "4x30min", "4x 30 mins", "four 30min sessions"
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:min|mins|minutes?)", t)
    if m:
        return round((float(m.group(1)) * float(m.group(2))) / 60, 2)

    # "2h30min", "2h 30m" → add
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)\s*(\d+(?:\.\d+)?)\s*(?:min|mins|minutes?)", t)
    if m:
        return round(float(m.group(1)) + float(m.group(2)) / 60, 2)

    # "half hour", "half an hour"
    if re.search(r"half\s+(?:an?\s+)?hour", t):
        return 0.5
    if re.search(r"quarter\s+(?:an?\s+)?hour", t):
        return 0.25

    # "2h", "1.5hr", "3 hours"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hours?)(?!\w)", t)
    if m:
        return float(m.group(1))

    # "30min", "45 minutes"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|mins|minutes?)(?!\w)", t)
    if m:
        return round(float(m.group(1)) / 60, 2)

    return None


# ── Type detection ─────────────────────────────────────────────────────────────

def detect_type(text: str) -> str:
    t = text.lower()
    # Score each type
    scores: dict[str, int] = defaultdict(int)
    for entry_type, keywords in TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                # Longer keyword = more specific = higher score
                scores[entry_type] += len(kw)
    if scores:
        return max(scores, key=lambda k: scores[k])
    # Fallback heuristics
    if any(w in t for w in ["develop", "implement", "code", "build", "fix", "bug", "feature", "task"]):
        return "Other"
    if any(w in t for w in ["test", "testing", "debug"]):
        return "Review"
    return "Other"


# ── Fuzzy matching for POD / Client ───────────────────────────────────────────

def fuzzy_match(text: str, options: list[str]) -> Optional[str]:
    """
    Match text against a list of options.
    Priority: exact match > whole word match > starts-with match
    """
    if not options:
        return None
    t = text.lower()

    # 1. Exact substring match
    for opt in sorted(options, key=len, reverse=True):
        if opt.lower() in t:
            return opt

    # 2. Word boundary match (handles "DPAI" in "DPAI-related work")
    for opt in sorted(options, key=len, reverse=True):
        pattern = r"\b" + re.escape(opt.lower()) + r"\b"
        if re.search(pattern, t):
            return opt

    # 3. Starts-with match for short codes (min 3 chars)
    words = re.findall(r"\b[a-zA-Z]{3,}\b", t)
    for word in words:
        for opt in options:
            if opt.lower().startswith(word.lower()) and len(word) >= 3:
                return opt

    return None


# ── Clean activity name ────────────────────────────────────────────────────────

def clean_activity(text: str, pods: list[str], clients: list[str]) -> str:
    """Strip hours/date/pod/client tokens to get a clean activity name."""
    t = text

    # Remove duration expressions
    t = re.sub(r"\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?\s*(?:min|mins|minutes?)", "", t, flags=re.I)
    t = re.sub(r"\d+(?:\.\d+)?\s*(?:h|hr|hrs|hours?)\s*\d+(?:\.\d+)?\s*(?:min|mins|minutes?)", "", t, flags=re.I)
    t = re.sub(r"\d+(?:\.\d+)?\s*(?:h|hr|hrs|hours?)", "", t, flags=re.I)
    t = re.sub(r"\d+(?:\.\d+)?\s*(?:min|mins|minutes?)", "", t, flags=re.I)
    t = re.sub(r"half\s+(?:an?\s+)?hour", "", t, flags=re.I)
    t = re.sub(r"quarter\s+(?:an?\s+)?hour", "", t, flags=re.I)

    # Remove date expressions
    t = re.sub(r"\b(?:today|yesterday|last\s+\w+|this\s+\w+)\b", "", t, flags=re.I)
    t = re.sub(r"\b(?:on\s+)?(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:\s+\d{4})?\b", "", t, flags=re.I)
    t = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", t)

    # Remove PODs and clients
    for item in sorted(pods + clients, key=len, reverse=True):
        t = re.sub(r"\b" + re.escape(item) + r"\b", "", t, flags=re.I)

    # Remove filler words
    t = re.sub(r"\b(on|for|in|at|with|then|had|have|did|worked|spent|done|doing|regarding|related|re:)\b", " ", t, flags=re.I)

    # Clean punctuation and whitespace
    t = re.sub(r"[,;:–—\-]+", " ", t)
    t = re.sub(r"\s{2,}", " ", t).strip()

    # Capitalise
    return t[:80].capitalize() if t else "Activity"


# ── Segment splitter ───────────────────────────────────────────────────────────

def split_segments(text: str) -> list[str]:
    """
    Split input into individual entry segments.
    Preserves date prefixes with their segments.
    """
    # Normalise line breaks and semicolons to commas
    text = re.sub(r"[\n;]+", ", ", text)

    # Split on comma, but NOT when inside "4x30min" style patterns
    parts = re.split(r",\s*(?:then\s+|and\s+)?", text)

    segments = []
    for part in parts:
        part = part.strip()
        if len(part) < 3:
            continue
        # If a segment has multiple day-colon prefixes, split further
        sub = re.split(r"(?<=[^:])(?=(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s*:)", part, flags=re.I)
        segments.extend(s.strip() for s in sub if len(s.strip()) >= 3)

    return segments


# ── Date prefix extractor ──────────────────────────────────────────────────────

def extract_date_prefix(segment: str, today: date) -> tuple[Optional[date], str]:
    """
    Detect and remove a date prefix like:
      "Monday: ...", "On Mar 13 ...", "Yesterday - ..."
    Returns (resolved_date_or_None, remaining_text)
    """
    # "Monday:", "Friday -", "Yesterday:"
    m = re.match(
        r"^(today|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun|last\s+\w+|this\s+\w+)\s*[:\-–]\s*",
        segment, re.I
    )
    if m:
        d = resolve_date(m.group(1), today)
        return d, segment[m.end():]

    # "On Mar 13, ...", "Mar 13 ..."
    m = re.match(
        r"^(?:on\s+)?((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:\s+\d{4})?)\s*[,:\-]?\s*",
        segment, re.I
    )
    if m:
        d = resolve_date(m.group(1), today)
        return d, segment[m.end():]

    # "2026-03-13: ..."
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\s*[,:\-]?\s*", segment)
    if m:
        d = resolve_date(m.group(1), today)
        return d, segment[m.end():]

    return None, segment


# ── Main parser function ───────────────────────────────────────────────────────

def parse_time_entries(
    text:    str,
    pods:    list[str],
    clients: list[str],
    today:   Optional[date] = None,
) -> dict:
    """
    Main entry point. Returns dict with entries + warnings.
    """
    if today is None:
        today = date.today()

    entries:  list[dict] = []
    warnings: list[str]  = []
    segments = split_segments(text)

    current_date = today  # carries over if a date prefix sets it

    for segment in segments:
        # Extract date prefix
        prefix_date, rest = extract_date_prefix(segment, today)
        if prefix_date:
            current_date = prefix_date

        # Try to get hours from the segment
        hours = parse_hours(rest) or parse_hours(segment)
        if not hours or hours <= 0:
            continue

        # Clamp unrealistic values
        if hours > 24:
            warnings.append(f'Unusually high hours ({hours}h) in: "{segment[:40]}" — please verify.')
            hours = min(hours, 24)

        pod    = fuzzy_match(rest, pods)    or fuzzy_match(segment, pods)
        client = fuzzy_match(rest, clients) or fuzzy_match(segment, clients)
        typ    = detect_type(rest)
        activity = clean_activity(rest, pods, clients)

        if len(activity) < 3:
            activity = clean_activity(segment, pods, clients)

        confidence = (
            "high"   if hours > 0 and len(activity) > 3 and (pod or client)
            else "medium" if hours > 0 and len(activity) > 3
            else "low"
        )

        entries.append({
            "date":       current_date.isoformat(),
            "activity":   activity,
            "hours":      round(hours * 4) / 4,  # round to nearest 0.25h
            "pod":        pod,
            "client":     client,
            "type":       typ,
            "notes":      "",
            "confidence": confidence,
        })

    # Warnings
    if not entries:
        warnings.append(
            'No entries parsed. Try: "sprint planning 2h DPAI Colgate, 1:1s 1h"'
        )
    else:
        no_pod_client = [e for e in entries if not e["pod"] and not e["client"]]
        if no_pod_client and pods:
            warnings.append(
                f"{len(no_pod_client)} entr{'y' if len(no_pod_client)==1 else 'ies'} "
                f"could not be matched to a POD or client — update them in the table."
            )

    total_hours = round(sum(e["hours"] for e in entries) * 4) / 4

    return {
        "entries":     entries,
        "total_hours": total_hours,
        "warnings":    warnings,
    }