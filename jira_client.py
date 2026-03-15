"""
Jira Client — fetches tickets from ALL projects, with all clients and PODs
"""

import requests
from requests.auth import HTTPBasicAuth
from collections import defaultdict


class JiraClient:
    CLIENT_FIELD = "customfield_10233"
    POD_FIELD    = "customfield_10193"

    def __init__(self, base_url, email, api_token, project_key=None):
        self.base_url    = base_url.rstrip("/")
        self.auth        = HTTPBasicAuth(email, api_token)
        self.headers     = {"Accept": "application/json"}
        self.project_key = project_key  # optional — if None, fetches ALL projects

    def _get(self, path, params=None):
        url = f"{self.base_url}/rest/api/3/{path}"
        print(f"\n🔵 API CALL: GET {url}")
        if params:
            for k, v in params.items():
                print(f"   {k}: {v}")
        r = requests.get(url, auth=self.auth, headers=self.headers, params=params)
        if r.ok:
            print(f"   ✅ Status: {r.status_code}")
        else:
            print(f"   ❌ Status: {r.status_code} — {r.text[:300]}")
        r.raise_for_status()
        return r.json()

    def fetch_all_project_keys(self):
        """Fetch all project keys the user has access to."""
        projects = []
        start_at = 0
        while True:
            data = self._get("project/search", params={
                "startAt":    start_at,
                "maxResults": 50,
                "orderBy":    "key",
            })
            batch = data.get("values", [])
            if not batch:
                break
            projects += [p["key"] for p in batch]
            start_at += 50
            if data.get("isLast", True) or start_at >= data.get("total", 0):
                break
        print(f"   📋 Found projects: {projects}")
        return projects

    def fetch_tickets(self, date_from=None, date_to=None):
        # Build JQL — if no project_key set, fetch ALL projects
        if self.project_key:
            jql = f"project = {self.project_key}"
        else:
            jql = "project is not EMPTY"  # all projects

        if date_from:
            jql += f" AND updated >= '{date_from}'"
        if date_to:
            jql += f" AND updated <= '{date_to}'"
        jql += " ORDER BY updated DESC"

        tickets         = []
        next_page_token = None

        while True:
            params = {
                "jql":        jql,
                "maxResults": 100,
                "fields": (
                    f"summary,assignee,status,timeoriginalestimate,"
                    f"timeestimate,timespent,worklog,"
                    f"{self.CLIENT_FIELD},{self.POD_FIELD},"
                    f"created,updated,issuetype,priority,project"
                )
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token
            else:
                params["startAt"] = 0

            data   = self._get("search/jql", params=params)
            issues = data.get("issues", [])
            print(f"   📦 Got {len(issues)} issues this page")

            if not issues:
                break

            for issue in issues:
                tickets.append(self._parse_issue(issue))

            next_page_token = data.get("nextPageToken")
            is_last         = data.get("isLast", True)

            if is_last or not next_page_token:
                break

        print(f"\n✅ Total tickets fetched: {len(tickets)}")
        return tickets

    def _parse_issue(self, issue):
        f   = issue["fields"]
        key = issue["key"]

        original_s  = f.get("timeoriginalestimate") or 0
        remaining_s = f.get("timeestimate") or 0
        spent_s     = f.get("timespent") or max(0, original_s - remaining_s)

        assignee   = f.get("assignee") or {}
        project    = issue.get("fields", {}).get("project", {})
        wl_data    = f.get("worklog", {})
        worklogs   = wl_data.get("worklogs", [])
        if wl_data.get("total", 0) > len(worklogs):
            worklogs = self._fetch_all_worklogs(key)

        parsed_wl = []
        for w in worklogs:
            author = w.get("author", {})
            parsed_wl.append({
                "author":  author.get("displayName", "Unknown"),
                "email":   author.get("emailAddress", ""),
                "date":    (w.get("started") or "")[:10],
                "hours":   round((w.get("timeSpentSeconds") or 0) / 3600, 2),
                "comment": self._extract_text(w.get("comment")),
            })

        return {
            "key":                      key,
            "project_key":              key.split("-")[0],
            "project_name":             project.get("name", key.split("-")[0]),
            "summary":                  f.get("summary", ""),
            "assignee":                 assignee.get("displayName", "Unassigned"),
            "assignee_email":           assignee.get("emailAddress", ""),
            "status":                   (f.get("status") or {}).get("name", ""),
            "client":                   self._extract_field(f.get(self.CLIENT_FIELD), default="SAAS"),
            "pod":                      self._extract_field(f.get(self.POD_FIELD), default=key.split("-")[0]),
            "hours_spent":              round(spent_s / 3600, 2),
            "original_estimate_hours":  round(original_s / 3600, 2),
            "remaining_estimate_hours": round(remaining_s / 3600, 2),
            "created":                  (f.get("created") or "")[:10],
            "updated":                  (f.get("updated") or "")[:10],
            "issue_type":               (f.get("issuetype") or {}).get("name", ""),
            "priority":                 (f.get("priority") or {}).get("name", ""),
            "url":                      f"{self.base_url}/browse/{key}",
            "worklogs":                 parsed_wl,
        }

    def _fetch_all_worklogs(self, issue_key):
        all_wl, start = [], 0
        while True:
            data    = self._get(f"issue/{issue_key}/worklog",
                                params={"startAt": start, "maxResults": 100})
            all_wl += data.get("worklogs", [])
            start  += 100
            if start >= data.get("total", 0):
                break
        return all_wl

    def _extract_field(self, val, default="Not Set"):
        if val is None:
            return default
        if isinstance(val, str):
            return val.strip() or "Not Set"
        if isinstance(val, dict):
            return (val.get("value") or val.get("name") or
                    val.get("displayName") or "Not Set")
        if isinstance(val, list):
            parts = [self._extract_field(v, default=default) for v in val]
            return ", ".join(p for p in parts if p != default) or "Not Set"
        return str(val)

    def _extract_text(self, doc):
        if not doc or isinstance(doc, str):
            return doc or ""
        texts = []
        for block in (doc.get("content") or []):
            for inline in (block.get("content") or []):
                if inline.get("type") == "text":
                    texts.append(inline.get("text", ""))
        return " ".join(texts).strip()

    def flat_worklog_rows(self, tickets):
        rows = []
        for t in tickets:
            if t["worklogs"]:
                for w in t["worklogs"]:
                    rows.append({
                        "name":    w["author"],
                        "pod":     t["pod"],
                        "date":    w["date"],
                        "module":  t["pod"],
                        "feature": t["summary"],
                        "type":    t["issue_type"] or "Feature",
                        "client":  t["client"],
                        "hours":   w["hours"],
                        "jira":    t["key"],
                        "remark":  w["comment"],
                    })
            else:
                rows.append({
                    "name":    t["assignee"],
                    "pod":     t["pod"],
                    "date":    t["updated"],
                    "module":  t["pod"],
                    "feature": t["summary"],
                    "type":    t["issue_type"] or "Feature",
                    "client":  t["client"],
                    "hours":   t["hours_spent"],
                    "jira":    t["key"],
                    "remark":  "",
                })
        return rows

    def filter_tickets(self, tickets, user=None, client=None, pod=None, project=None):
        if user:
            tickets = [t for t in tickets if t["assignee"] == user]
        if client:
            tickets = [t for t in tickets if t["client"] == client]
        if pod:
            tickets = [t for t in tickets if t["pod"] == pod]
        if project:
            tickets = [t for t in tickets if t["project_key"] == project]
        return tickets

    def group_by_user(self, tickets):
        g = defaultdict(lambda: {"hours": 0, "tickets": 0, "clients": set()})
        for t in tickets:
            g[t["assignee"]]["hours"]   += t["hours_spent"]
            g[t["assignee"]]["tickets"] += 1
            g[t["assignee"]]["clients"].add(t["client"])
        return [{"user": k, "hours": round(v["hours"], 2),
                 "tickets": v["tickets"], "clients": list(v["clients"])}
                for k, v in sorted(g.items(), key=lambda x: -x[1]["hours"])]

    def group_by_client(self, tickets):
        g = defaultdict(lambda: {"hours": 0, "tickets": 0, "users": set()})
        for t in tickets:
            g[t["client"]]["hours"]   += t["hours_spent"]
            g[t["client"]]["tickets"] += 1
            g[t["client"]]["users"].add(t["assignee"])
        return [{"client": k, "hours": round(v["hours"], 2),
                 "tickets": v["tickets"], "users": list(v["users"])}
                for k, v in sorted(g.items(), key=lambda x: -x[1]["hours"])]

    def group_by_pod(self, tickets):
        g = defaultdict(lambda: {"hours": 0, "tickets": 0, "clients": set()})
        for t in tickets:
            g[t["pod"]]["hours"]   += t["hours_spent"]
            g[t["pod"]]["tickets"] += 1
            g[t["pod"]]["clients"].add(t["client"])
        return [{"pod": k, "hours": round(v["hours"], 2),
                 "tickets": v["tickets"], "clients": list(v["clients"])}
                for k, v in sorted(g.items(), key=lambda x: -x[1]["hours"])]