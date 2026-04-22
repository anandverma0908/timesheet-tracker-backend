"""
app/services/github.py — GitHub API integration for code context.

Supports multiple repositories. Configure in backend .env:
  GITHUB_TOKEN=ghp_xxxxxxxxxxxx          (PAT with repo scope)
  GITHUB_REPOS=org/repo1,org/repo2,...   (comma-separated list)
"""

import asyncio
import httpx
from app.core.config import settings

_BASE = "https://api.github.com"
_TIMEOUT = 8.0


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_repos() -> list[str]:
    """Return list of configured repos, stripped of whitespace."""
    if not settings.github_repos:
        return []
    return [r.strip() for r in settings.github_repos.split(",") if r.strip()]


def is_configured() -> bool:
    return bool(settings.github_token and get_repos())


async def _search_code_in_repo(client: httpx.AsyncClient, repo: str, query: str) -> list[dict]:
    """Search files in a single repo."""
    q = f"{query} repo:{repo}"
    try:
        r = await client.get(f"{_BASE}/search/code", params={"q": q, "per_page": 5}, headers=_headers())
        if r.status_code != 200:
            return []
        return [
            {"path": i["path"], "url": i["html_url"], "repo": repo}
            for i in r.json().get("items", [])
        ]
    except Exception:
        return []


async def _search_prs_in_repo(client: httpx.AsyncClient, repo: str, ticket_key: str, title: str) -> list[dict]:
    """Search PRs in a single repo by ticket key, then by title keywords."""
    results = []
    for keyword in filter(None, [ticket_key, " ".join(title.split()[:4]) if title else ""]):
        q = f"{keyword} repo:{repo} type:pr"
        try:
            r = await client.get(f"{_BASE}/search/issues", params={"q": q, "per_page": 3}, headers=_headers())
            if r.status_code == 200:
                for i in r.json().get("items", []):
                    entry = {
                        "number": f"#{i['number']}",
                        "title": i["title"],
                        "status": (
                            "merged" if i.get("pull_request", {}).get("merged_at")
                            else "open" if i["state"] == "open"
                            else "closed"
                        ),
                        "url": i["html_url"],
                        "repo": repo,
                    }
                    # Deduplicate by URL
                    if not any(e["url"] == entry["url"] for e in results):
                        results.append(entry)
        except Exception:
            pass
        if results:
            break  # found results via ticket key — skip title fallback
    return results


async def _ai_search_terms(ticket_key: str, title: str, description: str) -> list[str]:
    """Ask AI to extract the best technical search terms for this ticket."""
    from app.ai.nova import chat
    prompt = (
        f'Ticket {ticket_key}: "{title}". '
        + (f'Description: {description[:300]}' if description else "")
        + "\n\nExtract 3-5 concise technical search terms suitable for searching a GitHub repository "
        "(file names, function names, module names, error strings). "
        'Return only a JSON array of strings, e.g. ["auth middleware", "token refresh", "SessionExpired"]'
    )
    try:
        raw = await chat(prompt, max_tokens=200)
        import json, re
        m = re.search(r'\[.*?\]', raw, re.DOTALL)
        if m:
            terms = json.loads(m.group(0))
            return [t.strip() for t in terms if isinstance(t, str)][:5]
    except Exception:
        pass
    # Fallback: use ticket key + title words
    return [ticket_key] + title.split()[:3]


async def search_all_repos(ticket_key: str, title: str, description: str = "") -> dict:
    """
    AI generates smart search terms, then searches all configured GitHub repos in parallel.
    Returns {"files": [...], "prs": [...]} aggregated and deduplicated.
    """
    repos = get_repos()
    if not repos:
        return {"files": [], "prs": []}

    # Let AI pick the best search terms
    search_terms = await _ai_search_terms(ticket_key, title, description)
    # Use the first (most relevant) term for code search, ticket key for PRs
    code_query = search_terms[0] if search_terms else (title or ticket_key)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        file_tasks = [_search_code_in_repo(client, repo, code_query) for repo in repos]
        pr_tasks   = [_search_prs_in_repo(client, repo, ticket_key, title) for repo in repos]
        file_results, pr_results = await asyncio.gather(
            asyncio.gather(*file_tasks),
            asyncio.gather(*pr_tasks),
        )

    files: list[dict] = []
    seen_files: set[str] = set()
    for batch in file_results:
        for f in batch:
            if f["url"] not in seen_files:
                seen_files.add(f["url"])
                files.append(f)

    prs: list[dict] = []
    seen_prs: set[str] = set()
    for batch in pr_results:
        for pr in batch:
            if pr["url"] not in seen_prs:
                seen_prs.add(pr["url"])
                prs.append(pr)

    return {"files": files[:10], "prs": prs[:8], "search_terms": search_terms}
