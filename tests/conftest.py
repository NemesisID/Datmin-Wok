from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel

from app import admin
from app.config import get_settings
from app.db import get_session
from app.main import app
from app.security import hash_password

PASSWORD = "rahasia-tes"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(engine, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password(PASSWORD))
    monkeypatch.setenv("SECRET_KEY", "kunci-tes")
    get_settings.cache_clear()
    admin.reset_limiter()

    def override_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    admin.reset_limiter()


def csrf_from(response) -> str:
    match = CSRF_RE.search(response.text)
    assert match, "Token CSRF tidak ditemukan di halaman"
    return match.group(1)


def login(client: TestClient) -> None:
    page = client.get("/admin/login")
    response = client.post(
        "/admin/login",
        data={
            "csrf_token": csrf_from(page),
            "username": "admin",
            "password": PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
