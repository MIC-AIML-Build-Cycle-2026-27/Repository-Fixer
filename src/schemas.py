"""Shared data contracts between the pipeline, LLM and frontend teams.

Keep these stable. If you change a field, tell the other teams first.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    QUEUED = "queued"
    ANALYZING = "analyzing"
    FIXING = "fixing"
    TESTING = "testing"
    PR_OPENED = "pr_opened"
    FAILED = "failed"


class IssueInfo(BaseModel):
    repo_full_name: str  # e.g. "my-org/my-repo"
    issue_number: int
    title: str
    body: str = ""


class CodeSnippet(BaseModel):
    path: str
    start_line: int
    end_line: int
    content: str


class TestResult(BaseModel):

    passed: bool
    output: str = ""
    duration_seconds: float = 0.0


# Pipeline -> LLM
class FixRequest(BaseModel):
    issue: IssueInfo
    snippets: list[CodeSnippet] = Field(default_factory=list)
    failing_test_output: str | None = None  # filled in on retry attempts
    attempt: int = 1


# LLM -> Pipeline
class FixProposal(BaseModel):
    explanation: str
    patch: str  # unified diff
    confidence: float = Field(ge=0.0, le=1.0)


# Pipeline -> Frontend
class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repo_full_name: str
    issue_number: int
    status: RunStatus
    attempts: int = 0
    pr_url: str | None = None
    created_at: datetime
