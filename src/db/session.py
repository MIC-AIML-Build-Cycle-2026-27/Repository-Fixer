"""Database engine/session helpers. The engine is created lazily so imports never need a DB."""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


def get_db():
    """FastAPI dependency: one session per request, always closed afterwards."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()
