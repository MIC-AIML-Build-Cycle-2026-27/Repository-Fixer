from src.db.models import Run
from src.worker import worker
from src.worker.llm import FakeLLMClient


def _add_run(db, status="queued", issue_number=5):
    run = Run(repo_full_name="org/repo", issue_number=issue_number, status=status)
    db.add(run)
    db.commit()
    return run


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


def test_process_run_goes_through_the_pipeline(db_session):
    run = _add_run(db_session)
    llm = RecordingLLM(db_session, run.id)

    worker.process_run(run.id, db_session, llm)

    assert llm.status_seen == "fixing"  # status was updated before the LLM call
    assert len(llm.requests) == 1
    assert llm.requests[0].issue.issue_number == 5
    assert llm.requests[0].issue.repo_full_name == "org/repo"
    refreshed = db_session.get(Run, run.id)
    assert refreshed.status == "testing"  # the later steps are stubs for now
    assert refreshed.attempts == 1


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


def test_llm_error_marks_run_failed(db_session):
    run = _add_run(db_session)

    worker.process_run(run.id, db_session, BrokenLLM())

    assert db_session.get(Run, run.id).status == "failed"


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
    from src.schemas import FixRequest, IssueInfo

    request = FixRequest(issue=IssueInfo(repo_full_name="a/b", issue_number=1, title="t"))
    proposal = FakeLLMClient().propose_fix(request)
    assert proposal.patch.startswith("--- a/")
    assert 0.0 <= proposal.confidence <= 1.0
