from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class TestStepSchema(BaseModel):
    step: str
    expected_result: str


# ── Test Cases ─────────────────────────────────────────────────────────────────

class TestCaseCreate(BaseModel):
    title: str
    description: Optional[str] = None
    preconditions: Optional[str] = None
    steps: Optional[List[TestStepSchema]] = None
    priority: Optional[str] = "medium"
    ticket_key: Optional[str] = None
    ticket_id: Optional[str] = None


class TestCaseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    preconditions: Optional[str] = None
    steps: Optional[List[TestStepSchema]] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    ticket_key: Optional[str] = None
    ticket_id: Optional[str] = None


class TestCaseOut(BaseModel):
    id: str
    org_id: str
    pod: str
    ticket_id: Optional[str] = None
    ticket_key: Optional[str] = None
    title: str
    description: Optional[str] = None
    preconditions: Optional[str] = None
    steps: Optional[List[dict]] = None
    priority: str
    status: str
    ai_generated: bool
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Test Cycles ────────────────────────────────────────────────────────────────

class TestCycleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    sprint_id: Optional[str] = None
    release_id: Optional[str] = None


class TestCycleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    sprint_id: Optional[str] = None
    release_id: Optional[str] = None


class TestCycleOut(BaseModel):
    id: str
    org_id: str
    pod: str
    name: str
    description: Optional[str] = None
    sprint_id: Optional[str] = None
    release_id: Optional[str] = None
    status: str
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    total: int = 0
    passed: int = 0
    failed: int = 0
    blocked: int = 0
    pending: int = 0

    model_config = {"from_attributes": True}


# ── Test Executions ────────────────────────────────────────────────────────────

class TestExecutionCreate(BaseModel):
    test_case_id: str


class TestExecutionUpdate(BaseModel):
    status: str
    notes: Optional[str] = None


class TestExecutionOut(BaseModel):
    id: str
    cycle_id: str
    test_case_id: str
    status: str
    executed_by: Optional[str] = None
    notes: Optional[str] = None
    executed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    test_case: Optional[TestCaseOut] = None

    model_config = {"from_attributes": True}


# ── AI Generate ───────────────────────────────────────────────────────────────

class GenerateTestCasesRequest(BaseModel):
    ticket_key: str
    ticket_summary: str
    ticket_description: Optional[str] = None
    count: Optional[int] = 5


class CoverageOut(BaseModel):
    total_tickets: int
    tested_tickets: int
    untested_tickets: int
    coverage_pct: float
    untested: List[dict]
    eos_insight: str
