import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api import webhook
from src.api.main import app
from src.config import Settings, get_settings
from src.db.models import Base
from src.db.session import get_db

WEBHOOK_SECRET = "test-secret"


@pytest.fixture
def db_session():
    """A throwaway in-memory SQLite database, so tests never need Postgres."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()


@pytest.fixture
def enqueued(monkeypatch):
    """Replaces the Valkey queue with a list, so tests never need Valkey."""
    ids: list[int] = []
    monkeypatch.setattr(webhook, "enqueue_run", ids.append)
    return ids


@pytest.fixture
def client(db_session, enqueued):
    app.dependency_overrides[get_settings] = lambda: Settings(
        github_webhook_secret=WEBHOOK_SECRET
    )
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()
