"""Tiny job queue on top of Valkey (a Redis-compatible store)."""

import valkey

from src.config import get_settings

QUEUE_KEY = "runs:queue"


def get_valkey() -> valkey.Valkey:
    return valkey.Valkey.from_url(get_settings().valkey_url, decode_responses=True)


def enqueue_run(run_id: int) -> None:
    get_valkey().lpush(QUEUE_KEY, str(run_id))


def dequeue_run(timeout: int = 5) -> int | None:
    """Block up to `timeout` seconds waiting for a run id. Used by the worker in Week 2."""
    item = get_valkey().brpop([QUEUE_KEY], timeout=timeout)
    return int(item[1]) if item else None
