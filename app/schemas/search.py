from pydantic import BaseModel
from typing import Optional, List


class SearchRequest(BaseModel):
    query: str
    scope: Optional[str] = "all"   # "all" | "tickets" | "wiki"
    limit: Optional[int] = 10


class SearchOut(BaseModel):
    results: List[dict]
    query:   str
    scope:   str


class NovaQueryRequest(BaseModel):
    query: str
    scope: Optional[str] = "all"


class NovaQueryOut(BaseModel):
    answer:  str
    sources: List[dict] = []
