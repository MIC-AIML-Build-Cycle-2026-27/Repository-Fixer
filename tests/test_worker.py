import shutil
import subprocess

import pytest

from src.db.models import Run
from src.github import publish
from src.github import repo as repo_module
from src.github.client import GitHubError
from src.schemas import FixRequest, IssueInfo
from src.schemas import TestResult as Result  # alias: pytest would try to collect "Test*"
from src.worker import worker
from src.worker.llm import FakeLLMClient

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

PASS = Result(passed=True, output="2 passed in 0.10s")
NEW_FAILURE = Result(
    passed=False,
    output="FAILED tests/test_a.py::test_x - AssertionError\n1 failed, 1 passed in 0.10s",
)
PR_URL = "https://github.com/org/repo/pull/1"


def _git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture(autouse=True)
def remote(tmp_path, monkeypatch):
    """A local bare repo stands in for GitHub: the worker clones from it and pushes to it."""
    src = tmp_path / "src"
    src.mkdir()
    _git("init", "-b", "main", cwd=src)
    (src / "README.md").write_bytes(b"# Demo\n")  # what FAKE_PATCH expects
    _git("add", ".", cwd=src)
    _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "init", cwd=src)
    bare = tmp_path / "remote.git"
    _git("clone", "--bare", str(src), str(bare), cwd=tmp_path)

    def local_url(repo_full_name, token=""):
        return str(bare)

    monkeypatch.setattr(repo_module, "github_clone_url", local_url)
    monkeypatch.setattr(publish, "github_clone_url", local_url)
    return bare


@pytest.fixture(autouse=True)
def sandbox(monkeypatch):
    """Replaces Docker. Set `sandbox.results`: one per call, the last one repeats."""

    class FakeSandbox:
        results = [PASS]
        calls = 0

        def __call__(self, repo_path, **kwargs):
            self.calls += 1
            return self.results[min(self.calls, len(self.results)) - 1]

    fake = FakeSandbox()
    monkeypatch.setattr(worker, "run_tests_in_docker", fake)
    return fake


class FakeGitHub:
    token = "fake-token"

    def __init__(self):
        self.comments = []
        self.prs = []

    def get_issue(self, repo_full_name, number):
        return IssueInfo(
            repo_full_name=repo_full_name,
            issue_number=number,
            title="Real title from GitHub",
            body="Real body",
        )

    def comment_on_issue(self, repo_full_name, number, body):
        self.comments.append(body)

    def create_pull_request(self, repo_full_name, head, base, title, body="", draft=False):
        self.prs.append({"head": head, "base": base, "title": title, "body": body, "draft": draft})
        return PR_URL


class BrokenGitHub(FakeGitHub):
    def get_issue(self, repo_full_name, number):
        raise GitHubError(404, "Not Found")


class RecordingLLM(FakeLLMClient):
    """Remembers what the run's status was at the moment the LLM was called."""

    def __init__(self, db, run_id):
        super().__init__()
        self.db = db
        self.run_id = run_id
        self.status_seen = None

    def propose_fix(self, request):
        self.status_seen = self.db.get(Run, self.run_id).status
        return super().propose_fix(request)


class BrokenLLM:
    def propose_fix(self, request):
        raise RuntimeError("LLM exploded")


def _add_run(db, status="queued", issue_number=5):
    run = Run(repo_full_name="org/repo", issue_number=issue_number, status=status)
    db.add(run)
    db.commit()
    return run


def test_successful_run_pushes_a_branch_and_opens_a_draft_pr(db_session, remote):
    run = _add_run(db_session)
    github = FakeGitHub()

    worker.process_run(run.id, db_session, FakeLLMClient(), github=github)

    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "pr_opened"
    assert refreshed.pr_url == PR_URL
    assert refreshed.attempts == 1

    branch = f"fix/issue-5-run-{run.id}"
    pushed = _git("--git-dir", str(remote), "show", f"{branch}:README.md", cwd=remote)
    assert "Fixed by Repository Fixer" in pushed

    [pr] = github.prs
    assert pr["head"] == branch
    assert pr["base"] == "main"
    assert pr["draft"] is True
    assert "Closes #5" in pr["body"]
    assert len(github.comments) == 2  # "working on it", then the PR link
    assert PR_URL in github.comments[-1]


def test_status_is_fixing_while_the_llm_runs(db_session):
    run = _add_run(db_session)
    llm = RecordingLLM(db_session, run.id)

    worker.process_run(run.id, db_session, llm, github=FakeGitHub())

    assert llm.status_seen == "fixing"
    assert llm.requests[0].issue.title == "Real title from GitHub"
    assert llm.requests[0].issue.body == "Real body"


def test_new_failure_is_retried_with_feedback(db_session, sandbox):
    sandbox.results = [PASS, NEW_FAILURE, PASS]  # baseline, attempt 1, attempt 2
    run = _add_run(db_session)
    llm = FakeLLMClient()

    worker.process_run(run.id, db_session, llm, github=FakeGitHub())

    assert db_session.get(Run, run.id).status == "pr_opened"
    assert db_session.get(Run, run.id).attempts == 2
    assert llm.requests[1].attempt == 2
    assert "tests/test_a.py::test_x" in llm.requests[1].failing_test_output


def test_failure_that_was_already_in_the_baseline_is_not_blamed_on_the_patch(
    db_session, sandbox
):
    sandbox.results = [NEW_FAILURE]  # fails before and after the patch
    run = _add_run(db_session)

    worker.process_run(run.id, db_session, FakeLLMClient(), github=FakeGitHub())

    assert db_session.get(Run, run.id).status == "pr_opened"


def test_run_fails_after_max_attempts(db_session, sandbox):
    sandbox.results = [PASS, NEW_FAILURE]
    run = _add_run(db_session)
    github = FakeGitHub()
    llm = FakeLLMClient()

    worker.process_run(run.id, db_session, llm, github=github)

    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "failed"
    assert refreshed.attempts == worker.MAX_ATTEMPTS
    assert len(llm.requests) == worker.MAX_ATTEMPTS
    assert github.prs == []
    assert "could not fix" in github.comments[-1]


def test_patch_that_does_not_apply_is_retried(db_session, sandbox):
    bad_patch = "--- a/missing.txt\n+++ b/missing.txt\n@@ -1 +1 @@\n-a\n+b\n"
    run = _add_run(db_session)
    llm = FakeLLMClient(patch=bad_patch)

    worker.process_run(run.id, db_session, llm, github=FakeGitHub())

    assert db_session.get(Run, run.id).status == "failed"
    assert llm.requests[1].failing_test_output.startswith("The patch did not apply")
    assert sandbox.calls == 1  # only the baseline: a patch that does not apply is not tested


def test_without_github_the_fix_is_found_but_no_pr_is_opened(db_session):
    run = _add_run(db_session, issue_number=9)
    llm = FakeLLMClient()

    worker.process_run(run.id, db_session, llm)

    assert llm.requests[0].issue.title == "Issue #9"  # placeholder issue
    assert db_session.get(Run, run.id).status == "failed"


def test_run_that_is_not_queued_is_skipped(db_session):
    run = _add_run(db_session, status="testing")
    llm = FakeLLMClient()

    worker.process_run(run.id, db_session, llm)

    assert llm.requests == []
    assert db_session.get(Run, run.id).status == "testing"


def test_missing_run_does_not_crash(db_session):
    llm = FakeLLMClient()
    worker.process_run(999, db_session, llm)
    assert llm.requests == []


def test_llm_error_marks_run_failed_and_comments(db_session):
    run = _add_run(db_session)
    github = FakeGitHub()

    worker.process_run(run.id, db_session, BrokenLLM(), github=github)

    assert db_session.get(Run, run.id).status == "failed"
    assert "internal error" in github.comments[-1]
    assert "exploded" not in github.comments[-1]  # details stay in the log


def test_github_error_marks_run_failed(db_session):
    run = _add_run(db_session)
    llm = FakeLLMClient()

    worker.process_run(run.id, db_session, llm, github=BrokenGitHub())

    assert db_session.get(Run, run.id).status == "failed"
    assert llm.requests == []


def test_run_once_handles_a_queued_job(db_session, monkeypatch):
    run = _add_run(db_session)
    monkeypatch.setattr(worker, "dequeue_run", lambda timeout=5: run.id)
    llm = FakeLLMClient()

    handled = worker.run_once(llm, session_factory=lambda: db_session)

    assert handled is True
    assert len(llm.requests) == 1


def test_run_once_returns_false_when_queue_is_empty(monkeypatch):
    monkeypatch.setattr(worker, "dequeue_run", lambda timeout=5: None)
    assert worker.run_once(FakeLLMClient()) is False


def test_fake_llm_returns_a_valid_proposal():
    request = FixRequest(issue=IssueInfo(repo_full_name="a/b", issue_number=1, title="t"))
    proposal = FakeLLMClient().propose_fix(request)
    assert proposal.patch.startswith("--- a/")
    assert 0.0 <= proposal.confidence <= 1.0


class CommentFailsGitHub(FakeGitHub):
    def comment_on_issue(self, repo_full_name, number, body):
        raise GitHubError(500, "Server Error")


def test_failing_comments_do_not_fail_the_run(db_session):
    run = _add_run(db_session)

    worker.process_run(run.id, db_session, FakeLLMClient(), github=CommentFailsGitHub())

    assert db_session.get(Run, run.id).status == "pr_opened"


def test_baseline_that_cannot_run_fails_before_asking_the_llm(db_session, sandbox):
    sandbox.results = [Result(passed=False, output="Tests timed out after 300s")]
    run = _add_run(db_session)
    github = FakeGitHub()
    llm = FakeLLMClient()

    worker.process_run(run.id, db_session, llm, github=github)

    assert db_session.get(Run, run.id).status == "failed"
    assert llm.requests == []
    assert "could not be run" in github.comments[-1]


def test_push_failure_marks_run_failed_without_a_pr(db_session, monkeypatch):
    def broken_push(*args, **kwargs):
        raise worker.GitError("git push failed: remote rejected")

    monkeypatch.setattr(worker, "push_branch", broken_push)
    run = _add_run(db_session)
    github = FakeGitHub()

    worker.process_run(run.id, db_session, FakeLLMClient(), github=github)

    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "failed"
    assert refreshed.pr_url is None
    assert github.prs == []
    assert "internal error" in github.comments[-1]


class LongWindedLLM(FakeLLMClient):
    def propose_fix(self, request):
        proposal = super().propose_fix(request)
        return proposal.model_copy(update={"explanation": "x" * 10_000})


def test_long_explanation_is_cut(db_session):
    run = _add_run(db_session)
    github = FakeGitHub()

    worker.process_run(run.id, db_session, LongWindedLLM(), github=github)

    body = github.prs[0]["body"]
    assert "x" * worker.MAX_EXPLANATION_CHARS in body
    assert "x" * (worker.MAX_EXPLANATION_CHARS + 1) not in body
