from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from src import jobs


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def brpop(self, keys, timeout=0):
        if self.error:
            raise self.error
        return self.result


def _use(monkeypatch, client, seen=None):
    def fake_get_valkey(socket_timeout=jobs.DEFAULT_SOCKET_TIMEOUT):
        if seen is not None:
            seen.append(socket_timeout)
        return client

    monkeypatch.setattr(jobs, "get_valkey", fake_get_valkey)


def test_dequeue_returns_run_id(monkeypatch):
    _use(monkeypatch, FakeClient(result=("runs:queue", "7")))
    assert jobs.dequeue_run(timeout=1) == 7


def test_dequeue_empty_queue_returns_none(monkeypatch):
    _use(monkeypatch, FakeClient(result=None))
    assert jobs.dequeue_run(timeout=1) is None


def test_socket_timeout_is_longer_than_the_blocking_wait(monkeypatch):
    seen = []
    _use(monkeypatch, FakeClient(result=None), seen)
    jobs.dequeue_run(timeout=5)
    assert seen[0] > 5


def test_valkey_timeout_is_not_an_error(monkeypatch):
    _use(monkeypatch, FakeClient(error=ValkeyTimeoutError("Timeout reading from socket")))
    assert jobs.dequeue_run(timeout=1) is None


def test_corrupt_entry_is_discarded(monkeypatch):
    _use(monkeypatch, FakeClient(result=("runs:queue", "not-a-number")))
    assert jobs.dequeue_run(timeout=1) is None
