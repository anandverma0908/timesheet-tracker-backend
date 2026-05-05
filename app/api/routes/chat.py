"""
app/api/routes/chat.py — Team Chat / Discussions.

Endpoints:
  GET    /api/chat/channels                       List channels visible to current user
  POST   /api/chat/channels                       Create a channel
  GET    /api/chat/channels/:id/messages          Paginated messages
  POST   /api/chat/channels/:id/messages          Send a message
  GET    /api/chat/channels/:id/members           List members of a channel
  POST   /api/chat/channels/:id/members           Add a member  (admin/EM/creator only)
  DELETE /api/chat/channels/:id/members/:user_id  Remove a member

Visibility rules:
  - Public channels  (is_private=False): visible to every org member.
  - Private channels (is_private=True):  visible ONLY to explicit members — no role bypass.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.chat import ChatChannel, ChatChannelMember, ChatMessage
from app.models.user import User

router = APIRouter(prefix="/api/chat", tags=["chat"])

_MANAGER_ROLES = {"admin", "engineering_manager"}


def _can_manage(user, channel: ChatChannel) -> bool:
    return user.role in _MANAGER_ROLES or str(channel.created_by) == str(user.id)


def _is_member(user_id: str, channel: ChatChannel) -> bool:
    return any(str(m.user_id) == str(user_id) for m in channel.memberships)


def _channel_dict(c: ChatChannel) -> dict:
    return {
        "id":           c.id,
        "org_id":       c.org_id,
        "name":         c.name,
        "type":         c.type,
        "pod":          c.pod,
        "created_by":   c.created_by,
        "member_count": len(c.memberships),
        "is_private":   c.is_private,
        "created_at":   c.created_at.isoformat() if c.created_at else None,
    }


# ── List channels ─────────────────────────────────────────────────────────────

@router.get("/channels")
async def list_channels(
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    channels = (
        db.query(ChatChannel)
        .filter(ChatChannel.org_id == user.org_id)
        .order_by(ChatChannel.type.desc(), ChatChannel.name)
        .all()
    )

    result = []
    for c in channels:
        if not c.is_private:
            result.append(_channel_dict(c))
        else:
            if _is_member(user.id, c):
                result.append(_channel_dict(c))

    return result


# ── Create channel ─────────────────────────────────────────────────────────────

@router.post("/channels")
async def create_channel(
    body: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    is_private = bool(body.get("is_private", False))

    channel = ChatChannel(
        org_id=user.org_id,
        name=body.get("name", "Untitled"),
        type=body.get("type", "general"),
        pod=body.get("pod"),
        created_by=user.id,
        is_private=is_private,
    )
    db.add(channel)
    db.flush()

    if is_private:
        # Add creator + any specified member_ids
        member_ids: list[str] = body.get("member_ids") or []
        all_ids = list({str(user.id)} | {str(m) for m in member_ids})
        for uid in all_ids:
            db.add(ChatChannelMember(channel_id=channel.id, user_id=uid, added_by=user.id))

    db.commit()
    db.refresh(channel)
    return _channel_dict(channel)


# ── Messages ──────────────────────────────────────────────────────────────────

@router.get("/channels/{channel_id}/messages")
async def list_messages(
    channel_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    channel = db.query(ChatChannel).filter(
        ChatChannel.id == channel_id, ChatChannel.org_id == user.org_id
    ).first()
    if not channel:
        raise HTTPException(404, "Channel not found")

    if channel.is_private and not _is_member(user.id, channel):
        raise HTTPException(403, "You are not a member of this channel")

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
                "id":           m.id,
                "channel_id":   m.channel_id,
                "user_id":      m.user_id,
                "author_name":  m.author.name if m.author else "Unknown",
                "author_email": m.author.email if m.author else None,
                "body":         m.body,
                "parent_id":    m.parent_id,
                "created_at":   m.created_at.isoformat() if m.created_at else None,
            }
            for m in reversed(messages)
        ],
        "limit":  limit,
        "offset": offset,
    }


@router.post("/channels/{channel_id}/messages")
async def send_message(
    channel_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    channel = db.query(ChatChannel).filter(
        ChatChannel.id == channel_id, ChatChannel.org_id == user.org_id
    ).first()
    if not channel:
        raise HTTPException(404, "Channel not found")

    if channel.is_private and not _is_member(user.id, channel):
        raise HTTPException(403, "You are not a member of this channel")

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
        "id":           msg.id,
        "channel_id":   msg.channel_id,
        "user_id":      msg.user_id,
        "author_name":  user.name,
        "author_email": user.email,
        "body":         msg.body,
        "parent_id":    msg.parent_id,
        "created_at":   msg.created_at.isoformat() if msg.created_at else None,
    }


# ── Members ───────────────────────────────────────────────────────────────────

@router.get("/channels/{channel_id}/members")
async def list_members(
    channel_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    channel = db.query(ChatChannel).filter(
        ChatChannel.id == channel_id, ChatChannel.org_id == user.org_id
    ).first()
    if not channel:
        raise HTTPException(404, "Channel not found")

    return [
        {
            "user_id":    m.user_id,
            "name":       m.user.name if m.user else "Unknown",
            "email":      m.user.email if m.user else None,
            "role":       m.user.role if m.user else None,
            "added_at":   m.added_at.isoformat() if m.added_at else None,
            "is_creator": str(m.user_id) == str(channel.created_by),
        }
        for m in channel.memberships
    ]


@router.post("/channels/{channel_id}/members")
async def add_member(
    channel_id: str,
    body: dict,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    channel = db.query(ChatChannel).filter(
        ChatChannel.id == channel_id, ChatChannel.org_id == user.org_id
    ).first()
    if not channel:
        raise HTTPException(404, "Channel not found")
    if not _can_manage(user, channel):
        raise HTTPException(403, "Only the channel creator or admin can manage members")

    target_user_id = body.get("user_id")
    if not target_user_id:
        raise HTTPException(400, "user_id is required")

    target = db.query(User).filter(User.id == target_user_id, User.org_id == user.org_id).first()
    if not target:
        raise HTTPException(404, "User not found in organisation")

    existing = db.query(ChatChannelMember).filter(
        ChatChannelMember.channel_id == channel_id,
        ChatChannelMember.user_id == target_user_id,
    ).first()
    if existing:
        return {"status": "already_member"}

    db.add(ChatChannelMember(channel_id=channel_id, user_id=target_user_id, added_by=user.id))
    db.commit()
    return {"status": "added", "user_id": target_user_id, "name": target.name}


@router.delete("/channels/{channel_id}")
async def delete_channel(
    channel_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    channel = db.query(ChatChannel).filter(
        ChatChannel.id == channel_id, ChatChannel.org_id == user.org_id
    ).first()
    if not channel:
        raise HTTPException(404, "Channel not found")
    if not _can_manage(user, channel):
        raise HTTPException(403, "Only the channel creator or admin can delete this channel")
    db.delete(channel)
    db.commit()
    return {"status": "deleted"}


@router.delete("/channels/{channel_id}/members/{target_user_id}")
async def remove_member(
    channel_id: str,
    target_user_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    channel = db.query(ChatChannel).filter(
        ChatChannel.id == channel_id, ChatChannel.org_id == user.org_id
    ).first()
    if not channel:
        raise HTTPException(404, "Channel not found")

    if str(target_user_id) != str(user.id) and not _can_manage(user, channel):
        raise HTTPException(403, "Only the channel creator or admin can remove members")

    membership = db.query(ChatChannelMember).filter(
        ChatChannelMember.channel_id == channel_id,
        ChatChannelMember.user_id == target_user_id,
    ).first()
    if not membership:
        raise HTTPException(404, "User is not a member")

    db.delete(membership)
    db.commit()
    return {"status": "removed"}
