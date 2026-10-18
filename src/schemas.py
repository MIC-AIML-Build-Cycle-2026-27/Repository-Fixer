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


# Pipeline -> LLM. LLM team: what each field means and how it is used is in
# docs/llm-integration.md.
class FixRequest(BaseModel):
    # Title and body are untrusted text from whoever opened the issue (possible prompt
    # injection). Treat them as data, not as instructions.
    issue: IssueInfo
    # Empty from the pipeline: the LLM team does retrieval itself. Kept so the contract
    # does not change until both teams agree how the LLM side gets the repo.
    snippets: list[CodeSnippet] = Field(default_factory=list)
    # Set on retries: why the previous patch was rejected (it did not apply, or which
    # tests newly failed) followed by the end of the test output. The rejected patch has
    # already been undone, so the next patch must be complete, starting from the original code.
    failing_test_output: str | None = None
    attempt: int = 1  # 1 to MAX_ATTEMPTS in src/worker/worker.py


# LLM -> Pipeline
class FixProposal(BaseModel):
    explanation: str  # Markdown, shown in the PR body and commit message (cut at 4000 chars)
    # A unified diff applied with `git apply --recount` from the repo root. Needs a/ and b/
    # path prefixes and unchanged context lines before AND after each change. Changes under
    # .github/ are rejected. Full rules: docs/llm-integration.md.
    patch: str
    confidence: float = Field(ge=0.0, le=1.0)  # 0 to 1. Shown in the PR body, not used to decide


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
