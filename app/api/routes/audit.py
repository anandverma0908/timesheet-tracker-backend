"""
app/api/routes/audit.py — Audit log query endpoint.

Endpoints:
  GET /api/audit-logs?entity_type=&action=&user_id=&limit=&offset=
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])


@router.get("")
async def list_audit_logs(
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
    entity_type: str = Query(None, description="Filter by entity type (e.g., jira_ticket)"),
    action: str = Query(None, description="Filter by action (e.g., created, updated, status_changed)"),
    user_id: str = Query(None, description="Filter by actor user ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Return audit log entries for the current organisation."""
    from app.models.audit import AuditLog
    from app.models.user import User

    q = (
        db.query(AuditLog, User.name.label("user_name"))
        .outerjoin(User, AuditLog.user_id == User.id)
        .filter(AuditLog.org_id == user.org_id)
    )

    if entity_type:
        q = q.filter(AuditLog.entity_type.ilike(f"%{entity_type}%"))
    if action:
        q = q.filter(AuditLog.action.ilike(f"%{action}%"))
    if user_id:
        q = q.filter(AuditLog.user_id == user_id)

    total = q.count()

    rows = (
        q.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [
            {
                "id": row.AuditLog.id,
                "entity_type": row.AuditLog.entity_type,
                "entity_id": row.AuditLog.entity_id,
                "user_id": row.AuditLog.user_id,
                "user_name": row.user_name or "System",
                "action": row.AuditLog.action,
                "diff": row.AuditLog.diff_json,
                "created_at": row.AuditLog.created_at.isoformat() if row.AuditLog.created_at else None,
            }
            for row in rows
        ],
    }
