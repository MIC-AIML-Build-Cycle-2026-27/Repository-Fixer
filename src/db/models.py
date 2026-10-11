"""Database tables."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from src.schemas import RunStatus


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    """One attempt to fix one GitHub issue."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(String(255))
    issue_number: Mapped[int]
    status: Mapped[str] = mapped_column(String(32), default=RunStatus.QUEUED.value)
    attempts: Mapped[int] = mapped_column(default=0)
    pr_url: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
