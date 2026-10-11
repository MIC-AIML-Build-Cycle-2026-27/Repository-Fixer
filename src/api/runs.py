"""Read endpoints for runs. The frontend team uses these."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import Run
from src.db.session import get_db
from src.schemas import RunSummary

router = APIRouter(tags=["runs"])


@router.get("/runs", response_model=list[RunSummary])
def list_runs(limit: int = 50, db: Session = Depends(get_db)):
    """Most recent runs first."""
    stmt = select(Run).order_by(Run.id.desc()).limit(min(limit, 200))
    return list(db.scalars(stmt))


@router.get("/runs/{run_id}", response_model=RunSummary)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run
