"""
app/api/routes/filters.py — Saved Filters CRUD.

Endpoints:
  GET    /api/filters          → list own + shared filters
  POST   /api/filters          → create filter
  DELETE /api/filters/{id}     → delete filter
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.saved_filter import SavedFilter

router = APIRouter(prefix="/api/filters", tags=["filters"])


class FilterCreatePayload(BaseModel):
    name: str
    filters: dict
    is_shared: bool = False


class FilterOut(BaseModel):
    id: str
    name: str
    filters: dict
    is_shared: bool
    created_at: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("", response_model=List[FilterOut])
async def list_filters(
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    """Return user's own filters + shared filters from the same org."""
    own = db.query(SavedFilter).filter(
        SavedFilter.user_id == user.id,
        SavedFilter.org_id == user.org_id,
    ).order_by(SavedFilter.created_at.desc()).all()

    shared = db.query(SavedFilter).filter(
        SavedFilter.org_id == user.org_id,
        SavedFilter.is_shared == True,
        SavedFilter.user_id != user.id,
    ).order_by(SavedFilter.created_at.desc()).all()

    results = []
    seen = set()
    for f in own + shared:
        if f.id in seen:
            continue
        seen.add(f.id)
        results.append(FilterOut(
            id=f.id,
            name=f.name,
            filters=f.filters,
            is_shared=f.is_shared,
            created_at=f.created_at.isoformat() if f.created_at else None,
        ))
    return results


@router.post("", response_model=FilterOut, status_code=201)
async def create_filter(
    payload: FilterCreatePayload,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    from app.models.base import gen_uuid
    f = SavedFilter(
        id=gen_uuid(),
        org_id=user.org_id,
        user_id=user.id,
        name=payload.name,
        filters=payload.filters,
        is_shared=payload.is_shared,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return FilterOut(
        id=f.id,
        name=f.name,
        filters=f.filters,
        is_shared=f.is_shared,
        created_at=f.created_at.isoformat() if f.created_at else None,
    )


@router.delete("/{filter_id}", status_code=204)
async def delete_filter(
    filter_id: str,
    db: Session = Depends(get_db),
    user = Depends(get_current_user),
):
    f = db.query(SavedFilter).filter(
        SavedFilter.id == filter_id,
        SavedFilter.org_id == user.org_id,
    ).first()
    if not f:
        raise HTTPException(404, "Filter not found")
    if f.user_id != user.id:
        raise HTTPException(403, "You can only delete your own filters")
    db.delete(f)
    db.commit()
