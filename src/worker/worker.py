"""The worker: takes run IDs from the queue and drives each run through the pipeline.

Start it with:  python -m src.worker.worker

Pipeline (stubs marked TODO are filled in over the next weeks):
    queued -> analyzing -> fixing -> testing -> pr_opened
                                           \\-> failed (on any error)
"""

import logging
import time
from collections.abc import Callable

from sqlalchemy.orm import Session

from src.db.models import Run
from src.db.session import get_session
from src.github.client import GitHubClient, get_github_client
from src.jobs import dequeue_run
from src.schemas import FixRequest, IssueInfo, RunStatus
from src.worker.llm import LLMClient, get_llm_client

log = logging.getLogger(__name__)


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
    # TODO: clone the repo and find relevant code (search, then Tree-sitter / Semgrep).
    return FixRequest(issue=issue, snippets=[])


def _mark_failed(db: Session, run: Run) -> None:
    try:
        db.rollback()
        run.status = RunStatus.FAILED.value
        db.commit()
    except Exception:
        log.exception("Could not mark run %s as failed", run.id)
        db.rollback()


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
        request = build_fix_request(run, github)

        set_status(db, run, RunStatus.FIXING)
        run.attempts += 1
        db.commit()
        proposal = llm.propose_fix(request)
        log.info("Run %s: got a proposal (confidence %.2f)", run_id, proposal.confidence)
        # TODO: apply proposal.patch to the cloned repo with `git apply`.

        set_status(db, run, RunStatus.TESTING)
        # TODO: run tests in the sandbox, compare with the baseline, retry on failure.
        # TODO: commit_all + push_branch (src/github/publish.py), then
        #       github.create_pull_request(...), set status PR_OPENED and run.pr_url.
        log.info("Run %s: pipeline stub finished (testing/PR steps not built yet)", run_id)
    except Exception:
        log.exception("Run %s failed", run_id)
        _mark_failed(db, run)


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
        log.warning("GITHUB_TOKEN is not set: issues will use placeholder text.")
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
