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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.code_review import CodeReviewSnapshot
from app.models.pr_review import PRReview
from app.models.ticket import JiraTicket
from app.ai.code_review import get_configured_repos, run_code_review, run_pr_review

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


# ── Pull-request review history ──────────────────────────────────────────────

def _pr_review_summary(row: PRReview) -> dict:
    return {
        "id":                  row.id,
        "github_repo":         row.github_repo,
        "pr_number":           row.pr_number,
        "pr_title":            row.pr_title,
        "pr_author":           row.pr_author,
        "pr_url":              row.pr_url,
        "base_branch":         row.base_branch,
        "head_branch":         row.head_branch,
        "linked_tickets":      row.linked_tickets or [],
        "linked_story_key":    row.linked_story_key,
        "requirement_context": row.requirement_context or {},
        "changed_files_count": len(row.changed_files or []),
        "status":              row.status,
        "total_count":         row.total_count,
        "critical_count":      row.critical_count,
        "high_count":          row.high_count,
        "medium_count":        row.medium_count,
        "created_at":          row.created_at.isoformat() if row.created_at else None,
        "analyzed_at":         row.analyzed_at.isoformat() if row.analyzed_at else None,
    }


@router.get("/pr-reviews")
def list_pr_reviews(
    repo: str = Query(..., description="github repo slug, e.g. org/repo"),
    limit: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(PRReview)
        .filter(
            PRReview.org_id == str(current_user.org_id),
            PRReview.github_repo == repo,
        )
        .order_by(PRReview.created_at.desc())
        .limit(limit)
        .all()
    )
    return {"pr_reviews": [_pr_review_summary(row) for row in rows]}


@router.get("/pr-reviews/{review_id}")
def get_pr_review(
    review_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = (
        db.query(PRReview)
        .filter(
            PRReview.id == review_id,
            PRReview.org_id == str(current_user.org_id),
        )
        .first()
    )
    if not review:
        raise HTTPException(status_code=404, detail="PR review not found")

    return {
        **_pr_review_summary(review),
        "changed_files": review.changed_files or [],
        "findings": review.findings or [],
    }


class LinkStoryRequest(BaseModel):
    ticket_key: str
    reanalyze: bool = True


def _ticket_requirement_context(ticket: JiraTicket) -> dict:
    return {
        "key": ticket.jira_key,
        "summary": ticket.summary,
        "description": ticket.description,
        "status": ticket.status,
        "issue_type": ticket.issue_type,
        "priority": ticket.priority,
        "story_points": ticket.story_points,
        "labels": ticket.labels or [],
        "pod": ticket.pod,
        "client": ticket.client,
    }


def _severity_counts(findings: list[dict]) -> tuple[int, int, int]:
    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    return critical, high, medium


async def _reanalyze_pr_review(review_id: str, org_id: str) -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        review = (
            db.query(PRReview)
            .filter(PRReview.id == review_id, PRReview.org_id == org_id)
            .first()
        )
        if not review:
            return
        review.status = "analyzing"
        db.commit()

        findings, changed_files = await run_pr_review(
            review.github_repo,
            review.pr_number,
            review.requirement_context or None,
        )
        critical, high, medium = _severity_counts(findings)
        review.findings = findings
        review.changed_files = changed_files
        review.total_count = len(findings)
        review.critical_count = critical
        review.high_count = high
        review.medium_count = medium
        review.status = "done"
        review.analyzed_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        review = db.query(PRReview).filter(PRReview.id == review_id, PRReview.org_id == org_id).first()
        if review:
            review.status = "failed"
            review.analyzed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.post("/pr-reviews/{review_id}/link-story")
def link_pr_review_story(
    review_id: str,
    body: LinkStoryRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = (
        db.query(PRReview)
        .filter(PRReview.id == review_id, PRReview.org_id == str(current_user.org_id))
        .first()
    )
    if not review:
        raise HTTPException(status_code=404, detail="PR review not found")

    ticket = (
        db.query(JiraTicket)
        .filter(
            JiraTicket.org_id == str(current_user.org_id),
            JiraTicket.jira_key == body.ticket_key.strip().upper(),
            JiraTicket.is_deleted == False,
        )
        .first()
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Story not found")

    context = _ticket_requirement_context(ticket)
    review.linked_story_key = ticket.jira_key
    review.requirement_context = context
    if ticket.jira_key not in (review.linked_tickets or []):
        review.linked_tickets = sorted([*(review.linked_tickets or []), ticket.jira_key])
    if body.reanalyze:
        review.status = "pending"
    db.commit()
    db.refresh(review)

    if body.reanalyze:
        background_tasks.add_task(_reanalyze_pr_review, review.id, str(current_user.org_id))

    return {
        **_pr_review_summary(review),
        "changed_files": review.changed_files or [],
        "findings": review.findings or [],
    }


@router.post("/pr-reviews/{review_id}/reanalyze")
def reanalyze_pr_review(
    review_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    review = (
        db.query(PRReview)
        .filter(PRReview.id == review_id, PRReview.org_id == str(current_user.org_id))
        .first()
    )
    if not review:
        raise HTTPException(status_code=404, detail="PR review not found")
    review.status = "pending"
    db.commit()
    background_tasks.add_task(_reanalyze_pr_review, review.id, str(current_user.org_id))
    return {"ok": True, "review_id": review.id, "status": review.status}
