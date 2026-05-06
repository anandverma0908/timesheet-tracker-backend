"""
EOS Code Review — AI-powered bug detection for any GitHub-configured repo.

Flow:
  1. Fetch the FULL file tree from GitHub (recursive)
  2. Filter eligible source files (all languages, skip generated/binary dirs)
  3. Fetch ALL file contents in parallel from GitHub API
  4. Split into batches of BATCH_SIZE files
  5. Run NOVA on each batch — one LLM call per batch
  6. Aggregate + deduplicate findings across all batches
  7. Return (findings, snapshot_id, scanned_files)

Why batching: LLMs have finite context windows. Batching lets us scan every
file in the repo while keeping each individual prompt small and reliable.
"""
import asyncio
import base64
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_GH_BASE = "https://api.github.com"
_GH_TIMEOUT = 30.0
_GH_FETCH_CONCURRENCY = 10   # parallel GitHub file fetches

# Source file extensions to analyse
_ALLOWED_EXT = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs",
    ".py", ".go", ".java", ".kt", ".rb", ".rs", ".cs", ".cpp", ".c",
}

# Directories that never contain analysable source code
_SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", ".turbo", ".cache",
    "coverage", "venv", ".venv", "__pycache__", ".mypy_cache", "target",
    "vendor", "out", "tmp", ".pytest_cache", "public", "assets",
    "migrations", "alembic", ".storybook", "storybook-static",
}

# Skip generated / declaration / test artefact files by suffix
_SKIP_SUFFIXES = {".d.ts", ".min.js", ".min.css", ".map", ".generated.ts"}

# Files per NOVA batch — keeps each prompt within comfortable context limits
_BATCH_SIZE = 8

# Per-file character limit (~750 tokens) — enough to see all logic, not waste context
_MAX_FILE_CHARS = 3500

_SYSTEM_PROMPT = (
    "You are EOS, a code review AI. Read the source files carefully and identify bugs. "
    "A bug is any code that will cause incorrect behaviour, broken navigation, ignored user actions, "
    "missing error handling, or unreachable UI states. "
    "Be thorough — it is better to report a likely bug than to miss a real one. "
    "Always cite the specific file and line number where the bug exists."
)

_BATCH_PROMPT_TMPL = """\
Review these source files from `{github_repo}` (batch {batch_num} of {total_batches}) and list all bugs you find.

{file_contents}

Respond with ONLY a JSON array. Start your response with [ and end with ].
Do not write any text before or after the JSON array.
If you find no bugs in this batch, respond with exactly: []

Each bug must use this structure:
[
  {{
    "id": "short-kebab-id",
    "title": "Bug title",
    "area": "Feature area (e.g. Auth, Dashboard, API, Routing)",
    "severity": "critical|high|medium",
    "summary": "One sentence: what is broken",
    "impact": "What the user experiences when this bug occurs",
    "whyValid": "Why this is definitely a bug, citing specific code",
    "evidence": ["code fact 1", "code fact 2", "code fact 3"],
    "reproduction": ["Step 1", "Step 2", "Step 3 — see the bug"],
    "files": [{{"path": "path/to/file.ts", "line": 42}}],
    "ticketDraft": {{
      "title": "Ticket title",
      "description": "Description with acceptance criteria",
      "labels": ["bug"],
      "pod": "Engineering"
    }}
  }}
]"""

_PR_SYSTEM_PROMPT = (
    "You are EOS, a senior AI code reviewer for Trackly. Review pull-request diffs with production judgment. "
    "Focus on issues introduced or exposed by the changed lines: correctness bugs, security problems, performance "
    "regressions, expensive renders or queries, broken API/UI contracts, missing error handling, incomplete work, "
    "and high-signal optimization or maintainability suggestions. Do not nitpick style. Always cite files and lines."
)

_PR_PROMPT_TMPL = """\
You are EOS reviewing a pull request to `{github_repo}`.
PR #{pr_number}: "{title}" by {author}
Branch: {head_branch} -> {base_branch}

Requirement / story context:
{requirement_context}

These files were changed in this PR. Each section includes GitHub's unified diff patch and, when available, the current file content at the PR head.

{file_context}

Find only high-signal findings introduced or exposed by these changes. Include:
- bugs and regressions
- requirement mismatches, missing acceptance criteria, and incomplete implementation against the linked story
- performance or scalability issues
- security/data-leak risks
- broken existing contracts between frontend/backend/modules
- incomplete PR work, missing migrations, missing route wiring, missing tests, or dead UI controls
- concrete optimizations when the current diff creates measurable waste or complexity

Respond with ONLY a JSON array. Start your response with [ and end with ].
If the PR looks clean, respond with exactly: []

Each finding must use this structure:
[
  {{
    "id": "short-kebab-id",
    "title": "Specific finding title",
    "area": "Feature area (e.g. Auth, API, Code Review, Performance)",
    "category": "bug|performance|security|optimization|contract|incomplete|test_gap",
    "severity": "critical|high|medium",
    "summary": "One sentence: what is wrong or risky",
    "impact": "What users, developers, or production systems experience",
    "whyValid": "Why this is valid, grounded in the patch/full content",
    "evidence": ["specific code fact 1", "specific code fact 2"],
    "reproduction": ["Step 1", "Step 2", "Expected vs actual"],
    "files": [{{"path": "path/to/file.ts", "line": 42}}],
    "suggestion": "Concrete fix or optimization direction",
    "ticketDraft": {{
      "title": "Ticket title",
      "description": "Description with acceptance criteria",
      "labels": ["bug"],
      "pod": "Engineering"
    }}
  }}
]"""


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _gh_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    return headers


def _is_eligible(path: str) -> bool:
    parts = path.split("/")
    # Skip excluded directories anywhere in the path
    if any(part in _SKIP_DIRS for part in parts):
        return False
    # Skip by suffix
    for suffix in _SKIP_SUFFIXES:
        if path.endswith(suffix):
            return False
    # Skip very long paths (usually generated)
    if len(parts) > 8:
        return False
    _, dot, ext = path.rpartition(".")
    return bool(dot) and f".{ext}" in _ALLOWED_EXT


async def _fetch_tree(client: httpx.AsyncClient, github_repo: str) -> list[dict]:
    url = f"{_GH_BASE}/repos/{github_repo}/git/trees/HEAD"
    resp = await client.get(url, params={"recursive": "1"}, headers=_gh_headers())
    resp.raise_for_status()
    data = resp.json()
    if data.get("truncated"):
        logger.warning("GitHub tree was truncated for %s — very large repo", github_repo)
    return [item for item in data.get("tree", []) if item.get("type") == "blob"]


async def _fetch_blob(client: httpx.AsyncClient, github_repo: str, item: dict) -> tuple[str, str]:
    """Fetch one blob and return (path, content). Returns ("", "") on error."""
    url = f"{_GH_BASE}/repos/{github_repo}/git/blobs/{item['sha']}"
    try:
        resp = await client.get(url, headers=_gh_headers())
        if resp.status_code != 200:
            return item["path"], ""
        data = resp.json()
        raw = data.get("content", "")
        if data.get("encoding") == "base64":
            content = base64.b64decode(raw.replace("\n", "")).decode("utf-8", errors="ignore")
        else:
            content = raw
        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + "\n... [truncated]"
        return item["path"], content
    except Exception as exc:
        logger.debug("Failed to fetch blob %s: %s", item["path"], exc)
        return item["path"], ""


async def _fetch_all_files(client: httpx.AsyncClient, github_repo: str, eligible: list[dict]) -> list[tuple[str, str]]:
    """Fetch all eligible files in parallel, return [(path, content)] sorted by path."""
    sem = asyncio.Semaphore(_GH_FETCH_CONCURRENCY)

    async def bounded_fetch(item: dict) -> tuple[str, str]:
        async with sem:
            return await _fetch_blob(client, github_repo, item)

    results = await asyncio.gather(*[bounded_fetch(item) for item in eligible])
    # Drop empty content
    return [(path, content) for path, content in results if content.strip()]


# ── JSON extraction ───────────────────────────────────────────────────────────

def _parse_findings(raw: str) -> list[dict]:
    """
    Extract a JSON array from NOVA's raw output.
    Local LLMs often wrap JSON in prose — try four strategies.
    """
    logger.debug("NOVA raw (first 400): %s", raw[:400])
    cleaned = raw.strip()

    # Strip markdown fences
    if "```" in cleaned:
        cleaned = re.sub(r"```[a-z]*\n?", "", cleaned).strip()

    # Strategy 1: direct parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return [f for f in data if isinstance(f, dict)]
        if isinstance(data, dict):
            return data.get("findings", [])
    except json.JSONDecodeError:
        pass

    # Strategy 2: extract outermost [ ... ]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start: end + 1])
            if isinstance(data, list):
                return [f for f in data if isinstance(f, dict)]
        except json.JSONDecodeError:
            pass

    # Strategy 3: extract outermost { ... }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start: end + 1])
            if isinstance(data, dict):
                return data.get("findings", [])
        except json.JSONDecodeError:
            pass

    logger.warning("Could not parse NOVA response as JSON. Raw[:300]:\n%s", raw[:300])
    return []


def _dedupe_findings(findings: list[dict]) -> list[dict]:
    """Deduplicate by id, generate id if missing."""
    seen: set[str] = set()
    result: list[dict] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or uuid.uuid4().hex[:10])
        if fid in seen:
            fid = f"{fid}-{uuid.uuid4().hex[:4]}"
        seen.add(fid)
        f["id"] = fid
        result.append(f)
    return result


def _normalise_finding(finding: dict, default_repo: str = "Engineering") -> dict:
    severity = str(finding.get("severity") or "medium").lower()
    if severity not in {"critical", "high", "medium"}:
        severity = "medium"
    files = finding.get("files") if isinstance(finding.get("files"), list) else []
    clean_files: list[dict] = []
    for file_ref in files:
        if not isinstance(file_ref, dict) or not file_ref.get("path"):
            continue
        line = file_ref.get("line")
        clean_files.append({
            "path": str(file_ref.get("path")),
            "line": int(line) if isinstance(line, int) or (isinstance(line, str) and line.isdigit()) else None,
        })

    ticket = finding.get("ticketDraft") if isinstance(finding.get("ticketDraft"), dict) else {}
    labels = ticket.get("labels") if isinstance(ticket.get("labels"), list) else []
    category = str(finding.get("category") or "bug").lower()
    if category not in {"bug", "performance", "security", "optimization", "contract", "incomplete", "test_gap"}:
        category = "bug"

    return {
        **finding,
        "severity": severity,
        "category": category,
        "title": str(finding.get("title") or "PR review finding"),
        "area": str(finding.get("area") or "Code Review"),
        "summary": str(finding.get("summary") or "EOS found an issue in this PR."),
        "impact": str(finding.get("impact") or "This may affect correctness, reliability, or maintainability."),
        "whyValid": str(finding.get("whyValid") or finding.get("summary") or "Grounded in the PR diff."),
        "evidence": [str(x) for x in finding.get("evidence", []) if x] or ["See affected file and patch context."],
        "reproduction": [str(x) for x in finding.get("reproduction", []) if x] or ["Review the changed code path called out by EOS."],
        "files": clean_files,
        "suggestion": str(finding.get("suggestion") or ""),
        "ticketDraft": {
            "title": str(ticket.get("title") or finding.get("title") or "Fix PR review finding"),
            "description": str(ticket.get("description") or finding.get("summary") or ""),
            "labels": [str(label) for label in labels] or [category.replace("_", "-")],
            "pod": str(ticket.get("pod") or default_repo),
        },
    }


async def _fetch_pull_request(client: httpx.AsyncClient, github_repo: str, pr_number: int) -> dict:
    url = f"{_GH_BASE}/repos/{github_repo}/pulls/{pr_number}"
    resp = await client.get(url, headers=_gh_headers())
    resp.raise_for_status()
    return resp.json()


async def _fetch_pr_files(client: httpx.AsyncClient, github_repo: str, pr_number: int) -> list[dict]:
    files: list[dict] = []
    page = 1
    while page <= 3:  # 300 files is far above the intended PR-review scope.
        url = f"{_GH_BASE}/repos/{github_repo}/pulls/{pr_number}/files"
        resp = await client.get(url, params={"per_page": 100, "page": page}, headers=_gh_headers())
        resp.raise_for_status()
        chunk = resp.json()
        if not isinstance(chunk, list) or not chunk:
            break
        files.extend(chunk)
        if len(chunk) < 100:
            break
        page += 1
    return files


async def _fetch_content_at_ref(
    client: httpx.AsyncClient,
    github_repo: str,
    path: str,
    ref: str,
) -> str:
    if not _is_eligible(path):
        return ""
    url = f"{_GH_BASE}/repos/{github_repo}/contents/{path}"
    try:
        resp = await client.get(url, params={"ref": ref}, headers=_gh_headers())
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        data = resp.json()
        if data.get("type") != "file":
            return ""
        raw = data.get("content", "")
        if data.get("encoding") == "base64":
            content = base64.b64decode(raw.replace("\n", "")).decode("utf-8", errors="ignore")
        else:
            content = raw
        if len(content) > _MAX_FILE_CHARS:
            content = content[:_MAX_FILE_CHARS] + "\n... [truncated]"
        return content
    except Exception as exc:
        logger.debug("Failed to fetch PR content %s@%s: %s", path, ref, exc)
        return ""


async def _build_pr_file_context(
    client: httpx.AsyncClient,
    github_repo: str,
    pr_files: list[dict],
    head_sha: str,
) -> tuple[str, list[str]]:
    eligible = [
        file
        for file in pr_files
        if file.get("status") != "removed" and _is_eligible(str(file.get("filename") or ""))
    ][:50]
    sem = asyncio.Semaphore(_GH_FETCH_CONCURRENCY)

    async def build_one(file: dict) -> tuple[str, str]:
        path = str(file.get("filename") or "")
        async with sem:
            content = await _fetch_content_at_ref(client, github_repo, path, head_sha)
        patch = str(file.get("patch") or "")
        if len(patch) > 5000:
            patch = patch[:5000] + "\n... [patch truncated]"
        section = (
            f"=== {path} (patch) ===\n{patch or '[No patch available from GitHub, likely binary or too large]'}\n\n"
            f"=== {path} (full content) ===\n{content or '[Content unavailable or skipped]'}"
        )
        return path, section

    results = await asyncio.gather(*[build_one(file) for file in eligible])
    changed_files = [path for path, _ in results]
    file_context = "\n\n".join(section for _, section in results)
    if len(file_context) > 120_000:
        file_context = file_context[:120_000] + "\n... [PR context truncated]"
    return file_context, changed_files


# ── Batch analysis ────────────────────────────────────────────────────────────

async def _analyse_batch(
    files: list[tuple[str, str]],
    github_repo: str,
    batch_num: int,
    total_batches: int,
) -> list[dict]:
    from app.ai.nova import chat

    file_contents = "\n\n".join(
        f"=== {path} ===\n{content}" for path, content in files
    )
    prompt = _BATCH_PROMPT_TMPL.format(
        github_repo=github_repo,
        batch_num=batch_num,
        total_batches=total_batches,
        file_contents=file_contents,
    )
    try:
        raw = await chat(
            user_message=prompt,
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=3000,
        )
    except Exception as exc:
        logger.error("NOVA call failed (batch %d/%d): %s", batch_num, total_batches, exc)
        return []

    findings = _parse_findings(raw)
    logger.info("Batch %d/%d → %d finding(s) from %d file(s)", batch_num, total_batches, len(findings), len(files))
    return findings


# ── Public API ────────────────────────────────────────────────────────────────

def get_configured_repos() -> list[str]:
    """Return list of 'org/repo' slugs from GITHUB_REPOS env setting."""
    return [r.strip() for r in settings.github_repos.split(",") if r.strip()]


async def run_code_review(github_repo: str) -> tuple[list[dict], str, list[str]]:
    """
    Scan an entire GitHub repo for bugs using batched NOVA analysis.

    Returns:
        findings      – aggregated, deduplicated list of CodeReviewFinding dicts
        snapshot_id   – human-readable run identifier
        scanned_files – every file path that was actually read
    """
    snapshot_id = (
        f"eos-{github_repo.replace('/', '-')}"
        f"-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')}"
    )

    # ── 1. Fetch file tree ────────────────────────────────────────────────────
    async with httpx.AsyncClient(timeout=_GH_TIMEOUT) as client:
        try:
            tree = await _fetch_tree(client, github_repo)
        except httpx.HTTPStatusError as exc:
            logger.error("GitHub tree fetch failed for %s: %s", github_repo, exc)
            return [], snapshot_id, []

        eligible = [item for item in tree if _is_eligible(item["path"])]
        if not eligible:
            logger.warning("No eligible source files found in %s", github_repo)
            return [], snapshot_id, []

        logger.info(
            "EOS: %d eligible files found in %s — fetching all in parallel",
            len(eligible), github_repo,
        )

        # ── 2. Fetch all file contents in parallel ────────────────────────────
        file_pairs = await _fetch_all_files(client, github_repo, eligible)

    scanned_files = [path for path, _ in file_pairs]
    logger.info("EOS: %d files with content, splitting into batches of %d", len(file_pairs), _BATCH_SIZE)

    if not file_pairs:
        logger.error("No file content retrieved from %s", github_repo)
        return [], snapshot_id, []

    # ── 3. Batch and analyse ──────────────────────────────────────────────────
    batches = [file_pairs[i: i + _BATCH_SIZE] for i in range(0, len(file_pairs), _BATCH_SIZE)]
    total_batches = len(batches)
    logger.info("EOS: analysing %d batch(es) for %s", total_batches, github_repo)

    all_findings: list[dict] = []
    for batch_num, batch in enumerate(batches, start=1):
        findings = await _analyse_batch(batch, github_repo, batch_num, total_batches)
        all_findings.extend(findings)

    # ── 4. Deduplicate and return ─────────────────────────────────────────────
    final = _dedupe_findings(all_findings)
    logger.info(
        "EOS complete: %d total findings across %d files (%d batches) — snapshot: %s",
        len(final), len(scanned_files), total_batches, snapshot_id,
    )
    return final, snapshot_id, scanned_files


def _format_requirement_context(requirement_context: Optional[dict]) -> str:
    if not requirement_context:
        return "No story was linked. Review against the PR title/body and changed code contracts."
    parts = [
        f"Story: {requirement_context.get('key') or 'linked story'}",
        f"Title: {requirement_context.get('summary') or ''}",
        f"Status: {requirement_context.get('status') or ''}",
        f"Type: {requirement_context.get('issue_type') or ''}",
        f"Priority: {requirement_context.get('priority') or ''}",
        f"Story points: {requirement_context.get('story_points') or ''}",
        "Description:",
        str(requirement_context.get("description") or "No description provided."),
    ]
    return "\n".join(parts)


async def run_pr_review(
    github_repo: str,
    pr_number: int,
    requirement_context: Optional[dict] = None,
) -> tuple[list[dict], list[str]]:
    """
    Review only files changed in a GitHub pull request using diff-focused EOS analysis.

    Returns:
        findings      – validated PR findings (bugs, perf, security, contracts, suggestions)
        changed_files – source files included in the PR review context
    """
    async with httpx.AsyncClient(timeout=_GH_TIMEOUT) as client:
        pull = await _fetch_pull_request(client, github_repo, pr_number)
        pr_files = await _fetch_pr_files(client, github_repo, pr_number)
        head_sha = pull.get("head", {}).get("sha") or pull.get("head", {}).get("ref") or "HEAD"
        file_context, changed_files = await _build_pr_file_context(client, github_repo, pr_files, head_sha)

    if not changed_files or not file_context.strip():
        logger.warning("No eligible changed source files found for %s PR #%s", github_repo, pr_number)
        return [], changed_files

    prompt = _PR_PROMPT_TMPL.format(
        github_repo=github_repo,
        pr_number=pr_number,
        title=pull.get("title") or "",
        author=(pull.get("user") or {}).get("login") or "unknown",
        head_branch=(pull.get("head") or {}).get("ref") or "",
        base_branch=(pull.get("base") or {}).get("ref") or "",
        requirement_context=_format_requirement_context(requirement_context),
        file_context=file_context,
    )

    from app.ai.nova import chat

    try:
        raw = await chat(
            user_message=prompt,
            system_prompt=_PR_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=4500,
        )
    except Exception as exc:
        logger.error("PR review NOVA call failed for %s PR #%s: %s", github_repo, pr_number, exc)
        raise

    findings = [_normalise_finding(f) for f in _parse_findings(raw)]
    final = _dedupe_findings(findings)
    logger.info(
        "EOS PR review complete: %d finding(s), %d changed file(s), %s PR #%s",
        len(final), len(changed_files), github_repo, pr_number,
    )
    return final, changed_files
