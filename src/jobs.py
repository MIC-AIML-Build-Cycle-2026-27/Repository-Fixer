"""Tiny job queue on top of Valkey (a Redis-compatible store)."""

import logging

import valkey
from valkey.exceptions import TimeoutError as ValkeyTimeoutError

from src.config import get_settings

log = logging.getLogger(__name__)

QUEUE_KEY = "runs:queue"

# The socket read timeout must be LONGER than the blocking wait in dequeue_run,
# otherwise an empty queue shows up as a timeout error.
DEFAULT_SOCKET_TIMEOUT = 5
SOCKET_TIMEOUT_MARGIN = 5


def get_valkey(socket_timeout: float | None = DEFAULT_SOCKET_TIMEOUT) -> valkey.Valkey:
    return valkey.Valkey.from_url(
        get_settings().valkey_url,
        decode_responses=True,
        socket_timeout=socket_timeout,
        socket_connect_timeout=DEFAULT_SOCKET_TIMEOUT,
    )


def enqueue_run(run_id: int) -> None:
    get_valkey().lpush(QUEUE_KEY, str(run_id))


def dequeue_run(timeout: int = 5) -> int | None:
    """Block up to `timeout` seconds waiting for a run id. Used by the worker."""
    client = get_valkey(socket_timeout=timeout + SOCKET_TIMEOUT_MARGIN)
    try:
        item = client.brpop([QUEUE_KEY], timeout=timeout)
    except ValkeyTimeoutError:
        # Nothing arrived in time. That is normal for an empty queue.
        return None
    if not item:
        return None
    try:
        return int(item[1])
    except (TypeError, ValueError):
        log.exception("Discarding corrupt queue entry %r", item[1])
        return None
