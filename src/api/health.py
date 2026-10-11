import logging

from fastapi import APIRouter
from sqlalchemy import text

from src.db.session import get_engine
from src.jobs import get_valkey

router = APIRouter(tags=["health"])

log = logging.getLogger(__name__)


@router.get("/health")
def health() -> dict:
    """Liveness check. Does not touch any external service."""
    return {"status": "ok"}


@router.get("/health/deps")
def health_deps() -> dict:
    """Checks that PostgreSQL and Valkey are reachable."""
    result = {}
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        result["postgres"] = "ok"
    except Exception as exc:
        log.exception("Postgres health check failed")
        result["postgres"] = f"error: {type(exc).__name__}: {exc}"

    try:
        get_valkey().ping()
        result["valkey"] = "ok"
    except Exception as exc:
        log.exception("Valkey health check failed")
        result["valkey"] = f"error: {type(exc).__name__}: {exc}"

    return result
