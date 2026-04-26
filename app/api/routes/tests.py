"""
app/api/routes/tests.py — Test case management with Nova AI generation.

Endpoints:
  GET    /api/spaces/{pod}/tests/cases
  POST   /api/spaces/{pod}/tests/cases
  PUT    /api/spaces/{pod}/tests/cases/{case_id}
  DELETE /api/spaces/{pod}/tests/cases/{case_id}
  POST   /api/spaces/{pod}/tests/cases/generate

  GET    /api/spaces/{pod}/tests/cycles
  POST   /api/spaces/{pod}/tests/cycles
  PUT    /api/spaces/{pod}/tests/cycles/{cycle_id}
  DELETE /api/spaces/{pod}/tests/cycles/{cycle_id}

  GET    /api/spaces/{pod}/tests/cycles/{cycle_id}/executions
  POST   /api/spaces/{pod}/tests/cycles/{cycle_id}/executions
  PUT    /api/spaces/{pod}/tests/executions/{exec_id}
  DELETE /api/spaces/{pod}/tests/executions/{exec_id}

  GET    /api/spaces/{pod}/tests/coverage
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.tests import TestCase, TestCycle, TestExecution
from app.models.ticket import JiraTicket
from app.schemas.tests import (
    TestCaseCreate, TestCaseUpdate, TestCaseOut,
    TestCycleCreate, TestCycleUpdate, TestCycleOut,
    TestExecutionCreate, TestExecutionUpdate, TestExecutionOut,
    GenerateTestCasesRequest, CoverageOut,
)
from app.ai.test_intelligence import generate_test_cases, generate_coverage_insight

router = APIRouter(prefix="/api/spaces", tags=["tests"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _case_to_out(tc: TestCase) -> TestCaseOut:
    return TestCaseOut(
        id=tc.id,
        org_id=tc.org_id,
        pod=tc.pod,
        ticket_id=tc.ticket_id,
        ticket_key=tc.ticket_key,
        title=tc.title,
        description=tc.description,
        preconditions=tc.preconditions,
        steps=tc.steps or [],
        priority=tc.priority,
        status=tc.status,
        ai_generated=tc.ai_generated,
        created_by=tc.created_by,
        created_at=tc.created_at,
        updated_at=tc.updated_at,
    )


def _cycle_to_out(cycle: TestCycle, db: Session, org_id: str) -> TestCycleOut:
    execs = db.query(TestExecution).filter(TestExecution.cycle_id == cycle.id).all()
    counts = {"pending": 0, "passed": 0, "failed": 0, "blocked": 0, "skipped": 0}
    for e in execs:
        counts[e.status] = counts.get(e.status, 0) + 1
    return TestCycleOut(
        id=cycle.id,
        org_id=cycle.org_id,
        pod=cycle.pod,
        name=cycle.name,
        description=cycle.description,
        sprint_id=cycle.sprint_id,
        release_id=cycle.release_id,
        status=cycle.status,
        created_by=cycle.created_by,
        created_at=cycle.created_at,
        updated_at=cycle.updated_at,
        total=len(execs),
        passed=counts["passed"],
        failed=counts["failed"],
        blocked=counts["blocked"],
        pending=counts["pending"],
    )


def _exec_to_out(ex: TestExecution, db: Session) -> TestExecutionOut:
    tc = db.query(TestCase).filter(TestCase.id == ex.test_case_id).first()
    return TestExecutionOut(
        id=ex.id,
        cycle_id=ex.cycle_id,
        test_case_id=ex.test_case_id,
        status=ex.status,
        executed_by=ex.executed_by,
        notes=ex.notes,
        executed_at=ex.executed_at,
        created_at=ex.created_at,
        updated_at=ex.updated_at,
        test_case=_case_to_out(tc) if tc else None,
    )


# ── Test Cases ─────────────────────────────────────────────────────────────────

@router.get("/{pod}/tests/cases", response_model=list[TestCaseOut])
async def list_test_cases(
    pod: str,
    ticket_key: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    q = db.query(TestCase).filter(
        TestCase.org_id == user.org_id,
        TestCase.pod == pod,
        TestCase.status != "archived",
    )
    if ticket_key:
        q = q.filter(TestCase.ticket_key == ticket_key)
    cases = q.order_by(TestCase.created_at.desc()).all()
    return [_case_to_out(c) for c in cases]


@router.post("/{pod}/tests/cases", response_model=TestCaseOut, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    pod: str,
    body: TestCaseCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tc = TestCase(
        org_id=user.org_id,
        pod=pod,
        ticket_id=body.ticket_id,
        ticket_key=body.ticket_key,
        title=body.title,
        description=body.description,
        preconditions=body.preconditions,
        steps=[s.model_dump() for s in body.steps] if body.steps else [],
        priority=body.priority or "medium",
        status="active",
        ai_generated=False,
        created_by=user.name or user.email,
    )
    db.add(tc)
    db.commit()
    db.refresh(tc)
    return _case_to_out(tc)


@router.put("/{pod}/tests/cases/{case_id}", response_model=TestCaseOut)
async def update_test_case(
    pod: str,
    case_id: str,
    body: TestCaseUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tc = db.query(TestCase).filter(
        TestCase.id == case_id,
        TestCase.org_id == user.org_id,
        TestCase.pod == pod,
    ).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Test case not found")
    for field, val in body.model_dump(exclude_none=True).items():
        if field == "steps" and val is not None:
            setattr(tc, field, [s if isinstance(s, dict) else s.model_dump() for s in val])
        else:
            setattr(tc, field, val)
    tc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(tc)
    return _case_to_out(tc)


@router.delete("/{pod}/tests/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    pod: str,
    case_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tc = db.query(TestCase).filter(
        TestCase.id == case_id,
        TestCase.org_id == user.org_id,
        TestCase.pod == pod,
    ).first()
    if not tc:
        raise HTTPException(status_code=404, detail="Test case not found")
    tc.status = "archived"
    tc.updated_at = datetime.utcnow()
    db.commit()


# ── AI Generate ───────────────────────────────────────────────────────────────

@router.post("/{pod}/tests/cases/generate", response_model=list[TestCaseOut])
async def generate_and_save(
    pod: str,
    body: GenerateTestCasesRequest,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    generated = await generate_test_cases(
        ticket_key=body.ticket_key,
        ticket_summary=body.ticket_summary,
        ticket_description=body.ticket_description,
        count=body.count or 5,
    )
    if not generated:
        raise HTTPException(status_code=502, detail="Nova failed to generate test cases")

    saved = []
    for item in generated:
        tc = TestCase(
            org_id=user.org_id,
            pod=pod,
            ticket_key=body.ticket_key,
            title=item.get("title", "Untitled"),
            description=item.get("description"),
            preconditions=item.get("preconditions"),
            steps=item.get("steps", []),
            priority=item.get("priority", "medium"),
            status="active",
            ai_generated=True,
            created_by=user.name or user.email,
        )
        db.add(tc)
        saved.append(tc)
    db.commit()
    for tc in saved:
        db.refresh(tc)
    return [_case_to_out(tc) for tc in saved]


# ── Test Cycles ────────────────────────────────────────────────────────────────

@router.get("/{pod}/tests/cycles", response_model=list[TestCycleOut])
async def list_cycles(
    pod: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    cycles = db.query(TestCycle).filter(
        TestCycle.org_id == user.org_id,
        TestCycle.pod == pod,
    ).order_by(TestCycle.created_at.desc()).all()
    return [_cycle_to_out(c, db, user.org_id) for c in cycles]


@router.post("/{pod}/tests/cycles", response_model=TestCycleOut, status_code=status.HTTP_201_CREATED)
async def create_cycle(
    pod: str,
    body: TestCycleCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    cycle = TestCycle(
        org_id=user.org_id,
        pod=pod,
        name=body.name,
        description=body.description,
        sprint_id=body.sprint_id,
        release_id=body.release_id,
        status="planning",
        created_by=user.name or user.email,
    )
    db.add(cycle)
    db.commit()
    db.refresh(cycle)
    return _cycle_to_out(cycle, db, user.org_id)


@router.put("/{pod}/tests/cycles/{cycle_id}", response_model=TestCycleOut)
async def update_cycle(
    pod: str,
    cycle_id: str,
    body: TestCycleUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    cycle = db.query(TestCycle).filter(
        TestCycle.id == cycle_id,
        TestCycle.org_id == user.org_id,
        TestCycle.pod == pod,
    ).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Test cycle not found")
    for field, val in body.model_dump(exclude_none=True).items():
        setattr(cycle, field, val)
    cycle.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(cycle)
    return _cycle_to_out(cycle, db, user.org_id)


@router.delete("/{pod}/tests/cycles/{cycle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cycle(
    pod: str,
    cycle_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    cycle = db.query(TestCycle).filter(
        TestCycle.id == cycle_id,
        TestCycle.org_id == user.org_id,
        TestCycle.pod == pod,
    ).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Test cycle not found")
    db.delete(cycle)
    db.commit()


# ── Test Executions ────────────────────────────────────────────────────────────

@router.get("/{pod}/tests/cycles/{cycle_id}/executions", response_model=list[TestExecutionOut])
async def list_executions(
    pod: str,
    cycle_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    cycle = db.query(TestCycle).filter(
        TestCycle.id == cycle_id,
        TestCycle.org_id == user.org_id,
    ).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Test cycle not found")
    execs = db.query(TestExecution).filter(
        TestExecution.cycle_id == cycle_id,
    ).order_by(TestExecution.created_at.asc()).all()
    return [_exec_to_out(e, db) for e in execs]


@router.post("/{pod}/tests/cycles/{cycle_id}/executions", response_model=TestExecutionOut, status_code=status.HTTP_201_CREATED)
async def add_to_cycle(
    pod: str,
    cycle_id: str,
    body: TestExecutionCreate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    cycle = db.query(TestCycle).filter(
        TestCycle.id == cycle_id,
        TestCycle.org_id == user.org_id,
    ).first()
    if not cycle:
        raise HTTPException(status_code=404, detail="Test cycle not found")
    existing = db.query(TestExecution).filter(
        TestExecution.cycle_id == cycle_id,
        TestExecution.test_case_id == body.test_case_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Test case already in this cycle")
    ex = TestExecution(
        cycle_id=cycle_id,
        test_case_id=body.test_case_id,
        status="pending",
    )
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return _exec_to_out(ex, db)


@router.put("/{pod}/tests/executions/{exec_id}", response_model=TestExecutionOut)
async def update_execution(
    pod: str,
    exec_id: str,
    body: TestExecutionUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    ex = db.query(TestExecution).filter(TestExecution.id == exec_id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="Execution not found")
    ex.status = body.status
    if body.notes is not None:
        ex.notes = body.notes
    ex.executed_by = user.name or user.email
    ex.executed_at = datetime.utcnow()
    ex.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ex)
    return _exec_to_out(ex, db)


@router.delete("/{pod}/tests/executions/{exec_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_from_cycle(
    pod: str,
    exec_id: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    ex = db.query(TestExecution).filter(TestExecution.id == exec_id).first()
    if not ex:
        raise HTTPException(status_code=404, detail="Execution not found")
    db.delete(ex)
    db.commit()


# ── Coverage ───────────────────────────────────────────────────────────────────

@router.get("/{pod}/tests/coverage", response_model=CoverageOut)
async def get_coverage(
    pod: str,
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    tickets = db.query(JiraTicket).filter(
        JiraTicket.org_id == user.org_id,
        JiraTicket.pod == pod,
        JiraTicket.is_deleted == False,
        JiraTicket.status.notin_(["Done", "Closed", "Cancelled"]),
    ).all()

    tested_keys = set(
        tc.ticket_key for tc in db.query(TestCase).filter(
            TestCase.org_id == user.org_id,
            TestCase.pod == pod,
            TestCase.status != "archived",
            TestCase.ticket_key.isnot(None),
        ).all()
    )

    untested = [t for t in tickets if t.jira_key not in tested_keys]
    total = len(tickets)
    tested = total - len(untested)
    coverage_pct = round((tested / total) * 100, 1) if total > 0 else 0.0

    eos_insight = await generate_coverage_insight(
        pod=pod,
        total=total,
        tested=tested,
        untested_summaries=[f"{t.jira_key}: {t.summary}" for t in untested],
    )

    return CoverageOut(
        total_tickets=total,
        tested_tickets=tested,
        untested_tickets=len(untested),
        coverage_pct=coverage_pct,
        untested=[{"key": t.jira_key, "summary": t.summary, "priority": t.priority, "assignee": t.assignee} for t in untested[:20]],
        eos_insight=eos_insight,
    )
