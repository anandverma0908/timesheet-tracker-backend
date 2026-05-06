"""
app/api/routes/webhooks.py — External webhook endpoints.
"""

import hmac
import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.ai.code_review import get_configured_repos, run_pr_review
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.dependencies import get_db
from app.models.organisation import Organisation
from app.models.pr_review import PRReview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

TICKET_PATTERN = re.compile(r"\b(TRK-\d+|TRKLY-\d+)\b", re.IGNORECASE)


def extract_ticket_refs(*texts: str) -> list[str]:
    found: set[str] = set()
    for text in texts:
        for match in TICKET_PATTERN.findall(text or ""):
            found.add(match.upper())
    return sorted(found)


def _verify_github_signature(body: bytes, signature: Optional[str]) -> None:
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=503, detail="GITHUB_WEBHOOK_SECRET is not configured")
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing GitHub signature")

    digest = hmac.new(
        settings.github_webhook_secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    expected = f"sha256={digest}"
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")


def _default_org_id(db: Session) -> str:
    org = db.query(Organisation).order_by(Organisation.created_at.asc()).first()
    if not org:
        raise HTTPException(status_code=400, detail="No organisation exists for PR review ownership")
    return str(org.id)


def _severity_counts(findings: list[dict]) -> tuple[int, int, int]:
    critical = sum(1 for f in findings if f.get("severity") == "critical")
    high = sum(1 for f in findings if f.get("severity") == "high")
    medium = sum(1 for f in findings if f.get("severity") == "medium")
    return critical, high, medium


async def run_pr_review_and_save(review_id: str) -> None:
    db = SessionLocal()
    try:
        review = db.query(PRReview).filter(PRReview.id == review_id).first()
        if not review:
            logger.warning("PR review %s disappeared before analysis", review_id)
            return

        review.status = "analyzing"
        db.commit()

        findings, changed_files = await run_pr_review(review.github_repo, review.pr_number)
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
    except Exception as exc:
        logger.exception("PR review %s failed: %s", review_id, exc)
        db.rollback()
        try:
            review = db.query(PRReview).filter(PRReview.id == review_id).first()
            if review:
                review.status = "failed"
                review.analyzed_at = datetime.utcnow()
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    body = await request.body()
    _verify_github_signature(body, request.headers.get("X-Hub-Signature-256"))

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return {"ok": True, "event": "ping"}
    if event != "pull_request":
        return {"ok": True, "ignored": event or "unknown"}

    payload = await request.json()
    action = payload.get("action")
    if action not in {"opened", "synchronize", "reopened"}:
        return {"ok": True, "ignored": action}

    repo = (payload.get("repository") or {}).get("full_name")
    pr = payload.get("pull_request") or {}
    if not repo or not pr.get("number"):
        raise HTTPException(status_code=400, detail="Malformed pull_request payload")

    configured = get_configured_repos()
    if configured and repo not in configured:
        return {"ok": True, "ignored": "repo_not_configured", "repo": repo}

    org_id = _default_org_id(db)
    linked_tickets = extract_ticket_refs(
        (pr.get("head") or {}).get("ref") or "",
        pr.get("title") or "",
        pr.get("body") or "",
    )

    review = (
        db.query(PRReview)
        .filter(
            PRReview.org_id == org_id,
            PRReview.github_repo == repo,
            PRReview.pr_number == int(pr["number"]),
        )
        .first()
    )
    if not review:
        review = PRReview(
            org_id=org_id,
            github_repo=repo,
            pr_number=int(pr["number"]),
        )
        db.add(review)

    review.pr_title = pr.get("title") or f"PR #{pr['number']}"
    review.pr_author = ((pr.get("user") or {}).get("login") or "")
    review.pr_url = pr.get("html_url") or ""
    review.base_branch = (pr.get("base") or {}).get("ref") or ""
    review.head_branch = (pr.get("head") or {}).get("ref") or ""
    review.linked_tickets = linked_tickets
    review.changed_files = []
    review.findings = []
    review.total_count = 0
    review.critical_count = 0
    review.high_count = 0
    review.medium_count = 0
    review.status = "pending"
    review.analyzed_at = None
    db.commit()
    db.refresh(review)

    background_tasks.add_task(run_pr_review_and_save, review.id)
    return {"ok": True, "review_id": review.id}
