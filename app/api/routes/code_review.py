"""
app/api/routes/code_review.py — EOS AI Code Review endpoints.

GET  /api/code-review/repos     List repos configured in GITHUB_REPOS env var
POST /api/code-review/analyze   Run AI code review on a selected repo
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.dependencies import get_current_user
from app.models.user import User
from app.ai.code_review import get_configured_repos, run_code_review

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code-review", tags=["code-review"])


@router.get("/repos")
async def list_repos(current_user: User = Depends(get_current_user)):
    """Return repos configured in the GITHUB_REPOS environment variable."""
    repos = get_configured_repos()
    return {
        "repos": [
            {"slug": slug, "name": slug.split("/")[-1], "full_name": slug}
            for slug in repos
        ]
    }


class AnalyzeRequest(BaseModel):
    github_repo: str


@router.post("/analyze")
async def analyze(body: AnalyzeRequest, current_user: User = Depends(get_current_user)):
    """
    Run an AI-powered code review on a GitHub repo.

    The repo must be listed in the GITHUB_REPOS environment variable.
    Uses the configured GITHUB_TOKEN to fetch file contents, then
    sends them to NOVA for structured bug analysis.
    """
    configured = get_configured_repos()
    if not configured:
        raise HTTPException(
            status_code=400,
            detail="No repos configured. Add GITHUB_REPOS=org/repo1,org/repo2 to your .env file.",
        )
    if body.github_repo not in configured:
        raise HTTPException(
            status_code=403,
            detail=f"Repo '{body.github_repo}' is not in the configured GITHUB_REPOS list.",
        )

    try:
        findings, snapshot_id, scanned_files = await run_code_review(body.github_repo)
    except Exception as exc:
        logger.error("Code review analysis failed for %s: %s", body.github_repo, exc)
        raise HTTPException(status_code=500, detail="Code review analysis failed")

    return {
        "snapshot_id": snapshot_id,
        "github_repo": body.github_repo,
        "scanned_files": scanned_files,
        "findings": findings,
        "debug": {
            "files_scanned": len(scanned_files),
            "findings_count": len(findings),
            "batches": (len(scanned_files) + 7) // 8,
        },
    }
