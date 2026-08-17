"""Tests for the AUTH_REQUIRED=false default: no login, a single local user
is attributed transparently. Mirrors the isolated-DB setup in test_auth.py.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core import api, auth
from core.db import Base, get_db

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def isolated_db(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_REQUIRED", False)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    api.app.dependency_overrides[get_db] = override_get_db
    yield
    api.app.dependency_overrides.pop(get_db, None)
    client.cookies.clear()


def test_me_succeeds_without_login():
    response = client.get("/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == auth.LOCAL_USER_EMAIL
    assert body["auth_required"] is False


def test_me_returns_same_local_user_across_requests():
    first = client.get("/auth/me").json()
    second = client.get("/auth/me").json()
    assert first["id"] == second["id"]
