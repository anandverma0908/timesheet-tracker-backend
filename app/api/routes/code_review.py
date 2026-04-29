"""
app/api/routes/code_review.py — EOS AI Code Review endpoints.

GET  /api/code-review/repos              List repos configured in GITHUB_REPOS env var
POST /api/code-review/analyze            Run AI code review and persist a snapshot
GET  /api/code-review/snapshots          List run history for a repo (latest first)
GET  /api/code-review/snapshots/{id}     Fetch full snapshot with findings
"""
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.code_review import CodeReviewSnapshot
from app.ai.code_review import get_configured_repos, run_code_review

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/code-review", tags=["code-review"])


# ── Repos ─────────────────────────────────────────────────────────────────────

@router.get("/repos")
async def list_repos(current_user: User = Depends(get_current_user)):
    repos = get_configured_repos()
    return {
        "repos": [
            {"slug": slug, "name": slug.split("/")[-1], "full_name": slug}
            for slug in repos
        ]
    }


# ── Analyze + auto-save snapshot ──────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    github_repo: str


@router.post("/analyze")
async def analyze(
    body: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
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

    # Persist the snapshot — use a fresh UUID as PK; store the engine's label separately
    critical  = sum(1 for f in findings if f.get("severity") == "critical")
    high      = sum(1 for f in findings if f.get("severity") == "high")
    medium    = sum(1 for f in findings if f.get("severity") == "medium")
    db_id     = str(uuid.uuid4())

    snap = CodeReviewSnapshot(
        id             = db_id,
        label          = snapshot_id,
        org_id         = str(current_user.org_id),
        github_repo    = body.github_repo,
        scanned_files  = scanned_files,
        findings       = findings,
        total_count    = len(findings),
        critical_count = critical,
        high_count     = high,
        medium_count   = medium,
        run_at         = datetime.utcnow(),
    )
    try:
        db.add(snap)
        db.commit()
        db.refresh(snap)
        saved_id = snap.id
    except Exception as exc:
        db.rollback()
        logger.warning("Could not persist code-review snapshot: %s", exc)
        saved_id = db_id

    return {
        "snapshot_id": saved_id,
        "github_repo": body.github_repo,
        "scanned_files": scanned_files,
        "findings": findings,
        "debug": {
            "files_scanned": len(scanned_files),
            "findings_count": len(findings),
            "batches": (len(scanned_files) + 7) // 8,
        },
    }


# ── Run history ───────────────────────────────────────────────────────────────

@router.get("/snapshots")
def list_snapshots(
    repo: str = Query(..., description="github repo slug, e.g. org/repo"),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CodeReviewSnapshot)
        .filter(
            CodeReviewSnapshot.org_id == str(current_user.org_id),
            CodeReviewSnapshot.github_repo == repo,
        )
        .order_by(CodeReviewSnapshot.run_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "snapshots": [
            {
                "id":                  r.id,
                "label":               r.label,
                "github_repo":         r.github_repo,
                "total_count":         r.total_count,
                "critical_count":      r.critical_count,
                "high_count":          r.high_count,
                "medium_count":        r.medium_count,
                "scanned_files_count": len(r.scanned_files or []),
                "run_at":              r.run_at.isoformat() if r.run_at else None,
            }
            for r in rows
        ]
    }


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(
    snapshot_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    snap = (
        db.query(CodeReviewSnapshot)
        .filter(
            CodeReviewSnapshot.id == snapshot_id,
            CodeReviewSnapshot.org_id == str(current_user.org_id),
        )
        .first()
    )
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return {
        "id":                  snap.id,
        "github_repo":         snap.github_repo,
        "total_count":         snap.total_count,
        "critical_count":      snap.critical_count,
        "high_count":          snap.high_count,
        "medium_count":        snap.medium_count,
        "scanned_files_count": len(snap.scanned_files or []),
        "scanned_files":       snap.scanned_files or [],
        "findings":            snap.findings or [],
        "run_at":              snap.run_at.isoformat() if snap.run_at else None,
    }
