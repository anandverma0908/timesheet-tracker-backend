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
