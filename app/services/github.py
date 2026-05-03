"""
app/services/github.py — Local multi-project code context retrieval.

Primary file discovery now happens against local git repos or local repo mirrors.
GitHub is used only as an enrichment layer for related PRs when a repo has a
known GitHub remote and a token is configured.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings

_BASE = "https://api.github.com"
_TIMEOUT = 12.0
_MAX_FILE_CANDIDATES = 60
_MAX_PRS = 8
_MAX_FILE_BYTES = 300_000
_MAX_FILE_CHARS = 24_000
_MAX_SNIPPET_LINES = 140

_ALLOWED_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".java", ".kt", ".go", ".rb", ".php",
    ".json", ".yml", ".yaml", ".toml", ".ini", ".env",
    ".css", ".scss", ".md",
}

_EXCLUDED_DIRS = {
    ".git", "node_modules", "dist", "build", ".next", ".turbo", ".cache",
    "coverage", "uploads", "venv", ".venv", "__pycache__", ".mypy_cache",
}

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in",
    "is", "it", "not", "of", "on", "or", "that", "the", "this", "to", "when",
    "with", "user", "page", "screen", "button", "feature", "working", "broken",
    "issue", "bug", "error", "fail", "fails", "failed", "cannot", "unable",
}

_REPO_INDEX_CACHE: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class RepoSource:
    name: str
    local_path: Path
    github_repo: str | None = None


def _json_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _safe_json_object(raw: str) -> dict[str, Any]:
    try:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
    except Exception:
        pass
    return {}


def _clean_term(term: str) -> str:
    term = re.sub(r"\s+", " ", (term or "").strip())
    term = term.strip("`\"'[](){}")
    return term[:80]


def _dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in terms:
        term = _clean_term(raw)
        key = term.lower()
        if not term or key in seen:
            continue
        seen.add(key)
        result.append(term)
    return result


def _keywords_from_text(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_./-]{2,}", text or "")
    preferred: list[str] = []
    for word in words:
        lower = word.lower()
        if lower in _STOPWORDS:
            continue
        preferred.append(word)
    return _dedupe_terms(preferred)[:limit]


def _tokenize_term(term: str) -> list[str]:
    return [
        token for token in re.split(r"[^a-z0-9]+", (term or "").lower())
        if len(token) > 2 and token not in _STOPWORDS
    ]


def _short_title_phrase(title: str) -> str:
    return " ".join((title or "").split()[:6]).strip()


def _ticket_text(ticket_key: str, title: str, description: str) -> str:
    return "\n".join(part for part in [ticket_key, title, description] if part).strip()


async def _ai_bug_signals(ticket_key: str, title: str, description: str) -> dict[str, Any]:
    from app.ai.nova import chat

    prompt = f"""
You are extracting bug-diagnosis signals for repository search.

Ticket key: {ticket_key}
Title: {title}
Description:
{description[:1200]}

Return only JSON with this shape:
{{
  "summary": "one sentence",
  "likely_layer": "frontend|backend|api|data|infra|unknown",
  "feature_area": "short phrase",
  "search_terms": ["specific technical term"],
  "error_terms": ["error text or status code"],
  "symbols": ["function/class/component names"],
  "paths": ["possible file or folder hints"],
  "related_terms": ["secondary search terms"]
}}

Rules:
- Prefer concrete code-facing terms from the ticket.
- Include UI names, routes, API hints, module ideas, or exact error strings when present.
- Do not explain anything outside the JSON.
""".strip()

    try:
        raw = await chat(prompt, temperature=0, max_tokens=300)
        parsed = _safe_json_object(raw)
    except Exception:
        parsed = {}

    title_terms = _keywords_from_text(title, limit=5)
    desc_terms = _keywords_from_text(description, limit=8)
    search_terms = _dedupe_terms(
        [ticket_key, _short_title_phrase(title)]
        + list(parsed.get("search_terms") or [])
        + list(parsed.get("error_terms") or [])
        + list(parsed.get("symbols") or [])
        + list(parsed.get("paths") or [])
        + list(parsed.get("related_terms") or [])
        + title_terms
        + desc_terms
    )[:12]

    return {
        "summary": parsed.get("summary") or (title or ticket_key or "Bug diagnosis"),
        "likely_layer": parsed.get("likely_layer") or "unknown",
        "feature_area": parsed.get("feature_area") or "",
        "search_terms": search_terms,
        "error_terms": _dedupe_terms(list(parsed.get("error_terms") or []))[:4],
        "symbols": _dedupe_terms(list(parsed.get("symbols") or []))[:5],
        "paths": _dedupe_terms(list(parsed.get("paths") or []))[:5],
        "related_terms": _dedupe_terms(list(parsed.get("related_terms") or []))[:5],
    }


def _backend_workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _parse_github_repo(url: str) -> str | None:
    text = (url or "").strip()
    patterns = [
        r"github\.com[:/](?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?$",
        r"api\.github\.com/repos/(?P<repo>[^/\s]+/[^/\s]+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group("repo")
    return None


def _run_git(args: list[str], cwd: Path, timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return ""


def _git_remote_urls(repo_path: Path) -> list[str]:
    output = _run_git(["remote", "-v"], repo_path)
    urls: list[str] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            urls.append(parts[1])
    return _dedupe_terms(urls)


def _git_head_signature(repo_path: Path) -> str:
    sig = _run_git(["rev-parse", "HEAD"], repo_path)
    if sig:
        return sig
    try:
        return str(repo_path.stat().st_mtime_ns)
    except Exception:
        return "unknown"


def _git_branch_name(repo_path: Path) -> str:
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return branch or "HEAD"


def _parse_local_repo_entries() -> list[RepoSource]:
    entries = [item.strip() for item in settings.code_context_local_repos.split(";") if item.strip()]
    repos: list[RepoSource] = []
    for entry in entries:
        parts = [part.strip() for part in entry.split("|")]
        if len(parts) == 3:
            name, path_str, github_repo = parts
        elif len(parts) == 2:
            name = Path(parts[0]).name
            path_str, github_repo = parts
        else:
            continue
        path = Path(path_str).expanduser().resolve()
        if path.exists() and path.is_dir():
            repos.append(RepoSource(name=name or path.name, local_path=path, github_repo=github_repo or None))
    return repos


def _search_roots() -> list[Path]:
    configured = [item.strip() for item in settings.code_context_repo_search_roots.split(";") if item.strip()]
    if configured:
        roots = [Path(item).expanduser().resolve() for item in configured]
    else:
        workspace_root = _backend_workspace_root()
        roots = [workspace_root, workspace_root.parent]
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if root.exists() and key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _candidate_git_dirs(root: Path) -> list[Path]:
    candidates: list[Path] = []
    if (root / ".git").exists():
        candidates.append(root)
    try:
        for child in root.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                if (child / ".git").exists():
                    candidates.append(child)
    except Exception:
        pass
    return candidates


def _auto_discover_repo_sources() -> list[RepoSource]:
    configured_github_repos = [
        repo.strip() for repo in settings.github_repos.split(",") if repo.strip()
    ]
    target_repos = set(configured_github_repos)
    discovered: list[RepoSource] = []
    seen_paths: set[str] = set()

    for root in _search_roots():
        for repo_dir in _candidate_git_dirs(root):
            path_key = str(repo_dir.resolve())
            if path_key in seen_paths:
                continue
            remote_urls = _git_remote_urls(repo_dir)
            remote_repos = [_parse_github_repo(url) for url in remote_urls]
            remote_repos = [repo for repo in remote_repos if repo]
            github_repo = next((repo for repo in remote_repos if repo in target_repos), None)
            if configured_github_repos and not github_repo:
                continue
            seen_paths.add(path_key)
            discovered.append(
                RepoSource(
                    name=repo_dir.name,
                    local_path=repo_dir.resolve(),
                    github_repo=github_repo or (remote_repos[0] if remote_repos else None),
                )
            )
    return discovered


def get_repo_sources() -> list[RepoSource]:
    configured = _parse_local_repo_entries()
    discovered = _auto_discover_repo_sources()
    merged: list[RepoSource] = []
    seen_paths: set[str] = set()
    seen_repos: set[str] = set()

    for source in configured + discovered:
        path_key = str(source.local_path)
        repo_key = source.github_repo or ""
        if path_key in seen_paths:
            continue
        if repo_key and repo_key in seen_repos:
            continue
        seen_paths.add(path_key)
        if repo_key:
            seen_repos.add(repo_key)
        merged.append(source)
    return merged


def is_configured() -> bool:
    return bool(get_repo_sources())


def _should_index_file(path: Path) -> bool:
    if path.suffix.lower() not in _ALLOWED_EXTENSIONS:
        return False
    if any(part in _EXCLUDED_DIRS for part in path.parts):
        return False
    try:
        size = path.stat().st_size
    except Exception:
        return False
    return 0 < size <= _MAX_FILE_BYTES


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:_MAX_FILE_CHARS]
    except Exception:
        return ""


def _extract_symbols(snippet: str) -> list[str]:
    patterns = [
        # JS / TS
        r"(?:export\s+default\s+function|export\s+function|function)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?:export\s+(?:default\s+)?class|class)\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(",
        # Python
        r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"^class\s+([A-Za-z_][A-Za-z0-9_]*)",
        # Java / Kotlin / Go
        r"(?:public|private|protected|internal|fun|func)\s+(?:static\s+)?(?:\w+\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    ]
    symbols: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, snippet, re.MULTILINE):
            symbols.append(match.group(1))
    return _dedupe_terms(symbols)[:12]


def _build_repo_index(source: RepoSource) -> list[dict[str, Any]]:
    signature = _git_head_signature(source.local_path)
    cache_key = str(source.local_path)
    cached = _REPO_INDEX_CACHE.get(cache_key)
    if cached and cached.get("signature") == signature:
        return cached["files"]

    files: list[dict[str, Any]] = []
    branch = _git_branch_name(source.local_path)
    for root, dirnames, filenames in os.walk(source.local_path):
        dirnames[:] = [name for name in dirnames if name not in _EXCLUDED_DIRS and not name.startswith(".")]
        root_path = Path(root)
        for filename in filenames:
            path = root_path / filename
            if not _should_index_file(path):
                continue
            relative = path.relative_to(source.local_path).as_posix()
            content = _read_text_file(path)
            if not content.strip():
                continue
            snippet_lines = [line.rstrip() for line in content.splitlines()[:_MAX_SNIPPET_LINES]]
            snippet = "\n".join(snippet_lines)
            symbols = _extract_symbols(snippet)
            files.append(
                {
                    "path": relative,
                    "repo": source.github_repo or source.name,
                    "repo_label": source.name,
                    "github_repo": source.github_repo,
                    "branch": branch,
                    "local_path": str(path),
                    "content": content,
                    "snippet": snippet,
                    "symbols": symbols,
                }
            )

    _REPO_INDEX_CACHE[cache_key] = {"signature": signature, "files": files}
    return files


def _layer_bonus(path: str, likely_layer: str) -> float:
    lower = path.lower()
    bonus = 0.0
    if likely_layer == "frontend":
        if lower.endswith(".tsx"):
            bonus += 1.4
        if lower.startswith("src/"):
            bonus += 1.0
        if any(part in lower for part in ["/features/", "/components/", "/services/", "/app/"]):
            bonus += 0.9
    elif likely_layer in {"backend", "api", "data"}:
        if lower.endswith(".py"):
            bonus += 1.4
        if any(part in lower for part in ["app/", "/api/", "/routes/", "/services/", "/models/", "/schemas/"]):
            bonus += 1.0
    return bonus


def _file_url(candidate: dict[str, Any]) -> str:
    github_repo = candidate.get("github_repo")
    branch = candidate.get("branch") or "HEAD"
    if github_repo:
        return f"https://github.com/{github_repo}/blob/{branch}/{candidate['path']}"
    return f"file://{candidate['local_path']}"


def _score_file_candidate(candidate: dict[str, Any], signals: dict[str, Any], terms: list[str]) -> dict[str, Any]:
    path_lower = candidate["path"].lower()
    content_lower = candidate["content"].lower()
    matched_terms: list[str] = []
    score = _layer_bonus(candidate["path"], signals.get("likely_layer") or "unknown")

    for term in terms:
        term_lower = term.lower()
        tokens = _tokenize_term(term)
        path_hits = 0
        content_hits = 0

        if term_lower and term_lower in path_lower:
            path_hits += 2
        if term_lower and term_lower in content_lower:
            content_hits += 2
        for token in tokens:
            if token in path_lower:
                path_hits += 1
            if token in content_lower:
                content_hits += 1

        if path_hits or content_hits:
            matched_terms.append(term)
            score += min(path_hits, 4) * 1.1
            score += min(content_hits, 4) * 0.55

    symbol_hits = [symbol for symbol in signals.get("symbols") or [] if symbol.lower() in content_lower]
    if symbol_hits:
        score += 1.2 + len(symbol_hits) * 0.4
        matched_terms.extend(symbol_hits)

    path_hints = [hint for hint in signals.get("paths") or [] if hint.lower() in path_lower]
    if path_hints:
        score += 1.0 + len(path_hints) * 0.4
        matched_terms.extend(path_hints)

    return {
        **candidate,
        "raw_score": round(score, 3),
        "matched_queries": _dedupe_terms(matched_terms)[:6],
    }


def _infer_symbol(snippet: str, signals: dict[str, Any]) -> str | None:
    for symbol in signals.get("symbols") or []:
        if symbol and symbol.lower() in (snippet or "").lower():
            return symbol
    extracted = _extract_symbols(snippet or "")
    return extracted[0] if extracted else None


def _compose_file_doc(ticket_text: str, candidate: dict[str, Any], signals: dict[str, Any]) -> str:
    return "\n".join(
        [
            ticket_text,
            f"Repo: {candidate['repo']}",
            f"Path: {candidate['path']}",
            f"Matched search terms: {', '.join(candidate.get('matched_queries') or [])}",
            f"Likely layer: {signals.get('likely_layer') or 'unknown'}",
            f"Feature area: {signals.get('feature_area') or ''}",
            f"Symbols: {', '.join(candidate.get('symbols') or [])}",
            candidate.get("snippet") or "",
        ]
    ).strip()


def _file_reason(candidate: dict[str, Any], signals: dict[str, Any], rerank_position: int) -> str:
    reasons: list[str] = []
    matched = candidate.get("matched_queries") or []
    if matched:
        reasons.append(f"matched {', '.join(matched[:2])}")
    if signals.get("feature_area"):
        reasons.append(f"aligned with {signals['feature_area']}")
    if candidate.get("symbol"):
        reasons.append(f"contains {candidate['symbol']}")
    if rerank_position == 0:
        reasons.append("best overall fit")
    return ", ".join(reasons[:3]) or "related code match"


def _confidence_from_rank(raw_score: float, rank_idx: int) -> float:
    confidence = min(0.97, 0.45 + min(raw_score, 8.0) * 0.05 - rank_idx * 0.05)
    return round(max(0.25, confidence), 2)


def _rank_file_candidates(
    ticket_key: str,
    title: str,
    description: str,
    signals: dict[str, Any],
    file_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not file_candidates:
        return []

    from app.ai.nova import rerank

    ticket_text = _ticket_text(ticket_key, title, description)
    docs = [_compose_file_doc(ticket_text, candidate, signals) for candidate in file_candidates]
    reranked_indices = rerank(ticket_text, docs, top_k=min(len(docs), 8))
    ordered = [file_candidates[idx] for idx in reranked_indices]
    for rank_idx, candidate in enumerate(ordered):
        candidate["symbol"] = _infer_symbol(candidate.get("snippet") or candidate.get("content") or "", signals)
        candidate["reason"] = _file_reason(candidate, signals, rank_idx)
        candidate["confidence"] = _confidence_from_rank(candidate.get("raw_score", 0), rank_idx)
        candidate["url"] = _file_url(candidate)
    return ordered[:6]


async def _search_pr_issues_in_repo(
    client: httpx.AsyncClient,
    repo: str,
    terms: list[str],
) -> list[dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for term in terms[:6]:
        query = f"{term} repo:{repo} type:pr"
        try:
            resp = await client.get(
                f"{_BASE}/search/issues",
                params={"q": query, "per_page": 4},
                headers=_json_headers(),
            )
            if resp.status_code != 200:
                continue
            items = resp.json().get("items", [])
        except Exception:
            continue

        for item in items:
            url = item.get("html_url")
            if not url:
                continue
            entry = results.setdefault(
                url,
                {
                    "number": item.get("number"),
                    "title": item.get("title") or "",
                    "url": url,
                    "repo": repo,
                    "matched_terms": [],
                },
            )
            entry["matched_terms"].append(term)
    return list(results.values())


async def _fetch_pr_details(client: httpx.AsyncClient, repo: str, number: int) -> dict[str, Any] | None:
    try:
        details_resp, files_resp = await asyncio.gather(
            client.get(f"{_BASE}/repos/{repo}/pulls/{number}", headers=_json_headers()),
            client.get(
                f"{_BASE}/repos/{repo}/pulls/{number}/files",
                params={"per_page": 100},
                headers=_json_headers(),
            ),
        )
        if details_resp.status_code != 200 or files_resp.status_code != 200:
            return None
        details = details_resp.json()
        files = files_resp.json()
        if not isinstance(details, dict) or not isinstance(files, list):
            return None
        return {"details": details, "files": files}
    except Exception:
        return None


def _pr_status(details: dict[str, Any]) -> str:
    if details.get("merged_at"):
        return "merged"
    if details.get("state") == "open":
        return "open"
    return "closed"


def _score_pr(
    pr_issue: dict[str, Any],
    pr_files: list[dict[str, Any]],
    candidate_files: list[dict[str, Any]],
) -> tuple[float, list[str], list[str]]:
    candidate_paths = {f["path"] for f in candidate_files if f.get("github_repo") == pr_issue["repo"]}
    candidate_basenames = {f["path"].split("/")[-1] for f in candidate_files}
    touched_paths = [f.get("filename") for f in pr_files if f.get("filename")]
    overlap = [path for path in touched_paths if path in candidate_paths]
    basename_overlap = [
        path for path in touched_paths
        if path.split("/")[-1] in candidate_basenames and path not in overlap
    ]

    score = len(pr_issue.get("matched_terms") or []) * 1.0
    score += len(overlap) * 2.6
    score += len(basename_overlap) * 0.9

    reasons: list[str] = []
    if overlap:
        reasons.append(f"touches {len(overlap)} predicted file(s)")
    if basename_overlap:
        reasons.append("touches nearby filenames")
    matched_terms = pr_issue.get("matched_terms") or []
    if matched_terms:
        reasons.append(f"matched {', '.join(matched_terms[:2])}")
    return score, reasons[:3], touched_paths[:8]


async def _rank_prs(
    client: httpx.AsyncClient,
    repos: list[str],
    ticket_key: str,
    title: str,
    signals: dict[str, Any],
    candidate_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not repos:
        return []

    terms = _dedupe_terms(
        [ticket_key, _short_title_phrase(title)]
        + list(signals.get("search_terms") or [])
        + [f["path"].split("/")[-1] for f in candidate_files[:4]]
    )[:8]

    issue_batches = await asyncio.gather(
        *[_search_pr_issues_in_repo(client, repo, terms) for repo in repos]
    )
    issues = [item for batch in issue_batches for item in batch]
    if not issues:
        return []

    unique_issues: dict[str, dict[str, Any]] = {}
    for issue in issues:
        existing = unique_issues.get(issue["url"])
        if existing:
            existing["matched_terms"] = _dedupe_terms(
                list(existing.get("matched_terms") or []) + list(issue.get("matched_terms") or [])
            )
        else:
            unique_issues[issue["url"]] = issue

    detail_tasks = [
        _fetch_pr_details(client, issue["repo"], int(issue["number"]))
        for issue in unique_issues.values()
    ]
    details_list = await asyncio.gather(*detail_tasks)

    ranked: list[dict[str, Any]] = []
    for issue, detail in zip(unique_issues.values(), details_list):
        if not detail:
            continue
        score, reasons, touched_files = _score_pr(issue, detail["files"], candidate_files)
        if score <= 0:
            continue
        details = detail["details"]
        ranked.append(
            {
                "number": f"#{details.get('number')}",
                "title": details.get("title") or issue["title"],
                "status": _pr_status(details),
                "url": details.get("html_url") or issue["url"],
                "repo": issue["repo"],
                "reason": ", ".join(reasons) or "related pull request match",
                "confidence": _confidence_from_rank(score, 0),
                "touched_files": touched_files,
                "_score": score,
            }
        )

    ranked.sort(key=lambda item: item["_score"], reverse=True)
    for item in ranked:
        item.pop("_score", None)
    return ranked[:_MAX_PRS]


def _all_repo_file_candidates(repo_sources: list[RepoSource], signals: dict[str, Any]) -> list[dict[str, Any]]:
    terms = _dedupe_terms(
        list(signals.get("search_terms") or [])
        + list(signals.get("error_terms") or [])
        + list(signals.get("symbols") or [])
        + list(signals.get("paths") or [])
        + _keywords_from_text(signals.get("feature_area") or "", limit=4)
    )[:14]

    candidates: list[dict[str, Any]] = []
    for source in repo_sources:
        files = _build_repo_index(source)
        for file_entry in files:
            scored = _score_file_candidate(file_entry, signals, terms)
            if scored["raw_score"] > 0:
                candidates.append(scored)

    candidates.sort(
        key=lambda item: (item["raw_score"], len(item.get("matched_queries") or [])),
        reverse=True,
    )
    if candidates:
        return candidates[:_MAX_FILE_CANDIDATES]

    # Fallback: nothing matched; still return a small layer-biased slice.
    fallback: list[dict[str, Any]] = []
    for source in repo_sources:
        files = _build_repo_index(source)
        for file_entry in files[:40]:
            scored = _score_file_candidate(file_entry, signals, [])
            fallback.append(scored)
    fallback.sort(key=lambda item: item["raw_score"], reverse=True)
    return fallback[:min(12, len(fallback))]


async def search_all_repos(ticket_key: str, title: str, description: str = "") -> dict[str, Any]:
    repo_sources = get_repo_sources()
    if not repo_sources:
        return {"files": [], "prs": [], "search_terms": []}

    signals = await _ai_bug_signals(ticket_key, title, description)
    raw_candidates = _all_repo_file_candidates(repo_sources, signals)
    ranked_files = _rank_file_candidates(
        ticket_key=ticket_key,
        title=title,
        description=description,
        signals=signals,
        file_candidates=raw_candidates,
    )

    github_repos = _dedupe_terms(
        [source.github_repo for source in repo_sources if source.github_repo]
    )
    if settings.github_token and github_repos:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            ranked_prs = await _rank_prs(
                client,
                repos=github_repos,
                ticket_key=ticket_key,
                title=title,
                signals=signals,
                candidate_files=ranked_files,
            )
    else:
        ranked_prs = []

    return {
        "files": [
            {
                "path": item["path"],
                "url": item["url"],
                "repo": item["repo"],
                "reason": item.get("reason"),
                "confidence": item.get("confidence"),
                "symbol": item.get("symbol"),
                "matched_terms": item.get("matched_queries") or [],
            }
            for item in ranked_files
        ],
        "prs": ranked_prs,
        "search_terms": signals.get("search_terms") or [],
        "diagnosis": {
            "summary": signals.get("summary") or title or ticket_key,
            "likely_layer": signals.get("likely_layer") or "unknown",
            "feature_area": signals.get("feature_area") or "",
            "repo_count": len(repo_sources),
        },
    }
