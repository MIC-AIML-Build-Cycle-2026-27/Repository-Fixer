from fastapi import APIRouter
from sqlalchemy import text

from src.db.session import get_engine
from src.jobs import get_valkey

router = APIRouter(tags=["health"])


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
        result["postgres"] = f"error: {type(exc).__name__}"

    try:
        get_valkey().ping()
        result["valkey"] = "ok"
    except Exception as exc:
        result["valkey"] = f"error: {type(exc).__name__}"

    return result
