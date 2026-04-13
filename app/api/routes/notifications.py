"""
app/api/routes/notifications.py — User notification management.

Endpoints:
  GET  /api/notifications             Unread notifications for current user
  POST /api/notifications/read-all    Mark all as read
  POST /api/notifications/:id/read    Mark single as read
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Return unread notifications for the current user (latest 50)."""
    from app.models.notification import Notification

    notifs = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).order_by(Notification.created_at.desc()).limit(50).all()

    return [
        {
            "id":         n.id,
            "type":       n.type,
            "title":      n.title,
            "body":       n.body,
            "link":       n.link,
            "is_read":    n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifs
    ]


@router.post("/read-all")
async def mark_all_read(
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Mark all of the current user's notifications as read."""
    from app.models.notification import Notification

    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read"}


@router.post("/{notification_id}/read")
async def mark_one_read(
    notification_id: str,
    db:   Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Mark a single notification as read."""
    from app.models.notification import Notification

    notif = db.query(Notification).filter(
        Notification.id      == notification_id,
        Notification.user_id == user.id,
    ).first()
    if not notif:
        raise HTTPException(404, "Notification not found")

    notif.is_read = True
    db.commit()
    return {"message": "Notification marked as read"}
