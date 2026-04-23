from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class WikiSpaceCreate(BaseModel):
    name:         str
    slug:         str
    description:  Optional[str] = None
    access_level: Optional[str] = "private"


class WikiSpaceUpdate(BaseModel):
    name:         Optional[str] = None
    description:  Optional[str] = None
    access_level: Optional[str] = None


class WikiSpaceOut(BaseModel):
    id:           str
    org_id:       str
    name:         str
    slug:         str
    description:  Optional[str] = None
    access_level: str
    created_at:   datetime

    model_config = {"from_attributes": True}


class WikiPageCreate(BaseModel):
    space_id:     str
    parent_id:    Optional[str] = None
    title:        str
    content_md:   Optional[str] = None
    content_html: Optional[str] = None


class WikiPageUpdate(BaseModel):
    title:        Optional[str] = None
    content_md:   Optional[str] = None
    content_html: Optional[str] = None
    parent_id:    Optional[str] = None


class WikiPageOut(BaseModel):
    id:           str
    space_id:     str
    org_id:       str
    parent_id:    Optional[str] = None
    title:        str
    content_md:   Optional[str] = None
    content_html: Optional[str] = None
    version:      int
    author_id:    Optional[str] = None
    author_name:  Optional[str] = None
    is_deleted:   bool = False
    created_at:   datetime
    updated_at:   datetime

    model_config = {"from_attributes": True}


class WikiVersionOut(BaseModel):
    id:          str
    page_id:     str
    version:     int
    content_md:  Optional[str] = None
    author_id:   Optional[str] = None
    author_name: Optional[str] = None
    created_at:  datetime

    model_config = {"from_attributes": True}


class MeetingNotesRequest(BaseModel):
    notes: Optional[str] = None
    content: Optional[str] = None


class MeetingNotesOut(BaseModel):
    action_items: List[dict]
    structured_md: Optional[str] = None
