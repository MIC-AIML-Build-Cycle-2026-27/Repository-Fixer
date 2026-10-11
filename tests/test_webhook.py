import hashlib
import hmac
import json

from src.api.webhook import verify_signature
from src.db.models import Run
from tests.conftest import WEBHOOK_SECRET


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _post(client, event: str, payload: dict):
    body = json.dumps(payload).encode()
    return client.post(
        "/webhook/github",
        content=body,
        headers={"X-GitHub-Event": event, "X-Hub-Signature-256": _sign(body)},
    )


ISSUE_OPENED = {
    "action": "opened",
    "issue": {"number": 7, "title": "Bug", "body": "It breaks"},
    "repository": {"full_name": "org/repo"},
}


def test_verify_signature_accepts_valid_and_rejects_invalid():
    body = b'{"a": 1}'
    secret = WEBHOOK_SECRET
    assert verify_signature(secret, body, _sign(body))
    assert not verify_signature(secret, body, "sha256=wrong")
    assert not verify_signature(secret, body, None)
    assert not verify_signature("", body, _sign(body))


def test_ping_with_valid_signature(client):
    response = _post(client, "ping", {})
    assert response.status_code == 202
    assert response.json() == {"message": "pong"}


def test_bad_signature_is_rejected(client):
    response = client.post(
        "/webhook/github",
        content=b"{}",
        headers={"X-GitHub-Event": "ping", "X-Hub-Signature-256": "sha256=bad"},
    )
    assert response.status_code == 401


def test_issue_opened_creates_run_and_enqueues_it(client, db_session, enqueued):
    response = _post(client, "issues", ISSUE_OPENED)

    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert enqueued == [run_id]

    run = db_session.get(Run, run_id)
    assert run.repo_full_name == "org/repo"
    assert run.issue_number == 7
    assert run.status == "queued"


def test_other_events_are_ignored(client, db_session, enqueued):
    response = _post(client, "issues", {**ISSUE_OPENED, "action": "closed"})
    assert response.json()["ignored"] is True
    assert enqueued == []


def test_queue_failure_marks_run_failed(client, db_session, monkeypatch):
    def broken_enqueue(run_id):
        raise ConnectionError("valkey is down")

    monkeypatch.setattr("src.api.webhook.enqueue_run", broken_enqueue)

    response = _post(client, "issues", ISSUE_OPENED)

    assert response.status_code == 503
    assert db_session.get(Run, 1).status == "failed"
