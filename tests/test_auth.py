"""Tests for the auth router (signup/login/logout/me). Uses an isolated
in-memory SQLite DB per test via a get_db dependency override, so these
tests never touch the real data/app.db file.
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
    # These tests exercise the real login/session flow, which only runs
    # when AUTH_REQUIRED is on - the fork-and-run default bypasses it
    # entirely via a single local user (see test_auth_optional.py).
    monkeypatch.setattr(auth, "AUTH_REQUIRED", True)

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


def test_signup_creates_user_and_session_cookie():
    response = client.post("/auth/signup", json={"email": "a@example.com", "password": "hunter22"})
    assert response.status_code == 200
    assert response.json() == {"id": 1, "email": "a@example.com", "auth_required": True}
    assert "session" in response.cookies


def test_signup_rejects_short_password():
    response = client.post("/auth/signup", json={"email": "a@example.com", "password": "short"})
    assert response.status_code == 400


def test_signup_rejects_duplicate_email():
    client.post("/auth/signup", json={"email": "a@example.com", "password": "hunter22"})
    response = client.post("/auth/signup", json={"email": "a@example.com", "password": "hunter22"})
    assert response.status_code == 409


def test_me_requires_authentication():
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user_after_signup():
    client.post("/auth/signup", json={"email": "a@example.com", "password": "hunter22"})
    response = client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == "a@example.com"


def test_login_with_correct_password_succeeds():
    client.post("/auth/signup", json={"email": "a@example.com", "password": "hunter22"})
    client.cookies.clear()
    response = client.post("/auth/login", json={"email": "a@example.com", "password": "hunter22"})
    assert response.status_code == 200
    assert "session" in response.cookies


def test_login_with_wrong_password_fails():
    client.post("/auth/signup", json={"email": "a@example.com", "password": "hunter22"})
    client.cookies.clear()
    response = client.post("/auth/login", json={"email": "a@example.com", "password": "wrongpass"})
    assert response.status_code == 401


def test_login_with_unknown_email_fails():
    response = client.post("/auth/login", json={"email": "nobody@example.com", "password": "hunter22"})
    assert response.status_code == 401


def test_logout_invalidates_session():
    client.post("/auth/signup", json={"email": "a@example.com", "password": "hunter22"})
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert client.get("/auth/me").status_code == 401
