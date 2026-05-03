"""
app/api/routes/chat.py — Team Chat / Discussions.

Endpoints:
  GET  /api/chat/channels              List channels for current org
  POST /api/chat/channels              Create a new channel
  GET  /api/chat/channels/:id/messages Paginated messages
  POST /api/chat/channels/:id/messages Send a message
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.chat import ChatChannel, ChatMessage

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.get("/channels")
async def list_channels(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Return all chat channels for the user's organisation."""
    channels = (
        db.query(ChatChannel)
        .filter(ChatChannel.org_id == user.org_id)
        .order_by(ChatChannel.type.desc(), ChatChannel.name)
        .all()
    )
    return [
        {
            "id": c.id,
            "org_id": c.org_id,
            "name": c.name,
            "type": c.type,
            "pod": c.pod,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in channels
    ]


@router.post("/channels")
async def create_channel(
    body: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Create a new chat channel."""
    channel = ChatChannel(
        org_id=user.org_id,
        name=body.get("name", "Untitled"),
        type=body.get("type", "general"),
        pod=body.get("pod"),
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return {
        "id": channel.id,
        "org_id": channel.org_id,
        "name": channel.name,
        "type": channel.type,
        "pod": channel.pod,
        "created_at": channel.created_at.isoformat() if channel.created_at else None,
    }


@router.get("/channels/{channel_id}/messages")
async def list_messages(
    channel_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Paginated messages for a channel (newest last)."""
    channel = (
        db.query(ChatChannel)
        .filter(ChatChannel.id == channel_id, ChatChannel.org_id == user.org_id)
        .first()
    )
    if not channel:
        raise HTTPException(404, "Channel not found")

    messages = (
        db.query(ChatMessage)
        .filter(ChatMessage.channel_id == channel_id, ChatMessage.parent_id.is_(None))
        .order_by(ChatMessage.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "messages": [
            {
                "id": m.id,
                "channel_id": m.channel_id,
                "user_id": m.user_id,
                "author_name": m.author.name if m.author else "Unknown",
                "author_email": m.author.email if m.author else None,
                "body": m.body,
                "parent_id": m.parent_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in reversed(messages)
        ],
        "limit": limit,
        "offset": offset,
    }


@router.post("/channels/{channel_id}/messages")
async def send_message(
    channel_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """Send a message to a channel."""
    channel = (
        db.query(ChatChannel)
        .filter(ChatChannel.id == channel_id, ChatChannel.org_id == user.org_id)
        .first()
    )
    if not channel:
        raise HTTPException(404, "Channel not found")

    msg = ChatMessage(
        channel_id=channel_id,
        user_id=user.id,
        body=body.get("body", ""),
        parent_id=body.get("parent_id"),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {
        "id": msg.id,
        "channel_id": msg.channel_id,
        "user_id": msg.user_id,
        "author_name": user.name,
        "author_email": user.email,
        "body": msg.body,
        "parent_id": msg.parent_id,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }
