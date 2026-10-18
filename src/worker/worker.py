"""The worker: takes run IDs from the queue and drives each run through the pipeline.

Start it with:  python -m src.worker.worker

One run:
    queued
    -> analyzing  read the issue, clone the repo, create the fix branch, and run the
                  tests once as a baseline (records the tests that already fail)
    -> fixing     ask the LLM for a patch and apply it
    -> testing    run the tests again; the fix counts only if no test fails that did not
                  already fail in the baseline. Otherwise back to fixing, with the failure
                  as feedback, up to MAX_ATTEMPTS times.
    -> pr_opened  commit, push the branch, open a draft PR, comment on the issue
    Any error, or running out of attempts -> failed (also commented on the issue).

The LLM is FakeLLMClient until the LLM team's client lands (see llm.py).
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from src.db.models import Run
from src.db.session import get_session
from src.github.client import GitHubClient, get_github_client
from src.github.publish import commit_all, push_branch
from src.github.repo import (
    GitError,
    apply_patch,
    checkout_branch,
    cloned_repo,
    current_branch,
    reset_hard,
)
from src.jobs import dequeue_run
from src.sandbox.runner import new_failures, pytest_ran, run_tests_in_docker, summary_line
from src.schemas import FixProposal, FixRequest, IssueInfo, RunStatus, TestResult
from src.worker.llm import LLMClient, get_llm_client

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
FEEDBACK_CHARS = 5000  # how much test output goes back to the LLM on a retry
# The explanation goes into the commit message (a command-line argument: Windows caps the
# whole command at 32,767 chars) and the PR body (GitHub caps it at 65,536).
MAX_EXPLANATION_CHARS = 4000


class FixFailed(Exception):
    """The pipeline worked but found no acceptable fix. The message is posted on the issue."""


def set_status(db: Session, run: Run, status: RunStatus) -> None:
    run.status = status.value
    db.commit()
    log.info("Run %s -> %s", run.id, status.value)


def build_fix_request(run: Run, github: GitHubClient | None = None) -> FixRequest:
    """Collect everything the LLM needs."""
    if github is not None:
        issue = github.get_issue(run.repo_full_name, run.issue_number)
    else:
        log.warning("No GitHub token configured, using a placeholder issue for run %s", run.id)
        issue = IssueInfo(
            repo_full_name=run.repo_full_name,
            issue_number=run.issue_number,
            title=f"Issue #{run.issue_number}",
            body="",
        )
    # The LLM team does retrieval (RAG) as well, so the pipeline does not fill `snippets`.
    # TODO: their client will need the cloned repo to search it. Agree with them how to pass
    #       it (e.g. a `repo_path` field on FixRequest, set after cloning in process_run).
    #       Until then the LLM gets the issue only.
    return FixRequest(issue=issue, snippets=[])


def _mark_failed(db: Session, run: Run) -> None:
    try:
        db.rollback()
        run.status = RunStatus.FAILED.value
        db.commit()
    except Exception:
        log.exception("Could not mark run %s as failed", run.id)
        db.rollback()


def _comment(github: GitHubClient | None, run: Run, text: str) -> None:
    """Best effort: a comment that fails to post must not fail the run."""
    if github is None:
        return
    try:
        github.comment_on_issue(run.repo_full_name, run.issue_number, text)
    except Exception:
        log.exception("Could not comment on the issue for run %s", run.id)


def find_fix(
    db: Session,
    run: Run,
    repo: Path,
    llm: LLMClient,
    request: FixRequest,
    baseline: TestResult,
) -> tuple[FixProposal, TestResult]:
    """Ask for a patch, apply it and test it, retrying with feedback. Raises FixFailed."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        set_status(db, run, RunStatus.FIXING)
        run.attempts = attempt
        db.commit()
        # Note for the LLM team: an exception here fails the whole run (it is not retried
        # here), so retry rate limits and timeouts inside your client. See docs/llm-integration.md.
        proposal = llm.propose_fix(request)
        log.info("Run %s attempt %s: confidence %.2f", run.id, attempt, proposal.confidence)

        try:
            apply_patch(repo, proposal.patch)
        except GitError as exc:
            feedback = f"The patch did not apply: {exc}"
        else:
            set_status(db, run, RunStatus.TESTING)
            result = run_tests_in_docker(repo)
            new = new_failures(baseline, result)
            if new == []:
                return proposal, result
            if new is None:
                feedback = "The tests did not finish after the patch."
            else:
                feedback = "These tests fail after the patch but not before it: " + ", ".join(new)
            feedback += "\n\n" + result.output[-FEEDBACK_CHARS:]
            # The next patch starts from the original code. Note for the LLM team: a retry
            # must send a complete patch, not a change on top of the rejected one.
            reset_hard(repo)

        log.info("Run %s attempt %s rejected: %s", run.id, attempt, feedback.splitlines()[0])
        request = request.model_copy(
            update={"attempt": attempt + 1, "failing_test_output": feedback}
        )
    raise FixFailed(f"No patch passed the tests in {MAX_ATTEMPTS} attempts.")


def publish_fix(
    run: Run,
    repo: Path,
    github: GitHubClient | None,
    base: str,
    branch: str,
    request: FixRequest,
    proposal: FixProposal,
    result: TestResult,
) -> str:
    """Commit, push and open a draft PR. Returns the PR's URL."""
    title = f"Fix #{run.issue_number}: {request.issue.title}"
    explanation = proposal.explanation.strip()[:MAX_EXPLANATION_CHARS]
    if not commit_all(repo, f"{title}\n\n{explanation}"):
        raise FixFailed("The patch made no changes.")
    if github is None:
        raise FixFailed("A fix passed the tests, but GITHUB_TOKEN is not set, so no PR was opened.")

    push_branch(repo, run.repo_full_name, branch, github.token)
    body = (
        f"Proposed fix for #{run.issue_number}, made by Repository Fixer (run #{run.id}).\n\n"
        f"{explanation}\n\n"
        f"- Attempts: {run.attempts}\n"
        f"- LLM confidence: {proposal.confidence:.2f}\n"
        f"- Tests after the fix: `{summary_line(result.output)}`\n\n"
        f"Closes #{run.issue_number}"
    )
    # Draft, because the patch comes from an LLM and a person must review it.
    return github.create_pull_request(
        run.repo_full_name, head=branch, base=base, title=title, body=body, draft=True
    )


def process_run(
    run_id: int, db: Session, llm: LLMClient, github: GitHubClient | None = None
) -> None:
    """Run the pipeline for one run. Never raises: problems end up as status 'failed'."""
    run = db.get(Run, run_id)
    if run is None:
        log.warning("Run %s not found, skipping", run_id)
        return
    if run.status != RunStatus.QUEUED.value:
        log.info("Run %s is already '%s', skipping", run_id, run.status)
        return

    try:
        set_status(db, run, RunStatus.ANALYZING)
        _comment(github, run, f"Repository Fixer is working on this issue (run #{run.id}).")
        request = build_fix_request(run, github)

        token = github.token if github is not None else ""
        with cloned_repo(run.repo_full_name, token=token) as repo:
            base = current_branch(repo)  # a fresh clone is on the default branch
            # The run id keeps branch names unique when the same issue is tried again.
            branch = f"fix/issue-{run.issue_number}-run-{run.id}"
            checkout_branch(repo, branch)

            baseline = run_tests_in_docker(repo)
            log.info("Run %s baseline: %s", run.id, summary_line(baseline.output))
            if not pytest_ran(baseline):
                # Every attempt would time out or crash the same way, so stop now.
                raise FixFailed(
                    "The repository's tests could not be run in the sandbox (timeout or "
                    "crash), so no fix could be checked."
                )

            proposal, result = find_fix(db, run, repo, llm, request, baseline)
            run.pr_url = publish_fix(run, repo, github, base, branch, request, proposal, result)

        set_status(db, run, RunStatus.PR_OPENED)
        _comment(github, run, f"Opened a draft pull request with a proposed fix: {run.pr_url}")
    except FixFailed as exc:
        log.warning("Run %s failed: %s", run_id, exc)
        _mark_failed(db, run)
        _comment(github, run, f"Repository Fixer could not fix this issue: {exc}")
    except Exception:
        # Details stay in the log: exception text can include internal hosts or paths.
        log.exception("Run %s failed", run_id)
        _mark_failed(db, run)
        _comment(github, run, f"Repository Fixer stopped on an internal error (run #{run.id}).")


def run_once(
    llm: LLMClient,
    session_factory: Callable[[], Session] = get_session,
    timeout: int = 5,
    github: GitHubClient | None = None,
) -> bool:
    """Wait up to `timeout` seconds for one job. Returns True if a job was handled."""
    run_id = dequeue_run(timeout=timeout)
    if run_id is None:
        return False
    db = session_factory()
    try:
        process_run(run_id, db, llm, github)
    finally:
        db.close()
    return True


def run_forever(llm: LLMClient | None = None, github: GitHubClient | None = None) -> None:
    llm = llm or get_llm_client()
    github = github or get_github_client()
    if github is None:
        log.warning("GITHUB_TOKEN is not set: placeholder issues, and no PRs can be opened.")
    # TODO: before the loop, mark runs left in analyzing/fixing/testing as failed. A crash
    #       or Ctrl+C mid-run leaves them there (the job is already off the queue), and
    #       process_run only picks up 'queued' runs, so they would never finish.
    #       Also re-queue runs still 'queued' with no queue entry: run_once loses the job
    #       if opening a DB session fails right after it was popped.
    log.info("Worker started, waiting for runs. Press Ctrl+C to stop.")
    while True:
        try:
            run_once(llm, github=github)
        except KeyboardInterrupt:
            log.info("Worker stopped.")
            break
        except Exception:
            log.exception("Worker loop error, retrying in 2 seconds")
            time.sleep(2)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    run_forever()
