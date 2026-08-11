from collections.abc import Generator

import pytest
from app.db import get_session
from app.main import app
from app.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def test_task_lifecycle(client: TestClient) -> None:
    created = client.post("/tasks", json={"title": "Read request lifecycle"})
    assert created.status_code == 201
    assert created.headers["location"] == "/tasks/1"
    assert created.json()["completed"] is False

    updated = client.patch("/tasks/1", json={"completed": True})
    assert updated.status_code == 200
    assert updated.json()["completed"] is True

    listed = client.get("/tasks", params={"limit": 10, "offset": 0})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [1]

    deleted = client.delete("/tasks/1")
    assert deleted.status_code == 204
    assert client.get("/tasks/1").status_code == 404


def test_validation_and_missing_resource(client: TestClient) -> None:
    assert client.post("/tasks", json={"title": ""}).status_code == 422
    assert client.patch("/tasks/999", json={"completed": True}).status_code == 404
    assert client.get("/tasks", params={"limit": 101}).status_code == 422


def test_patch_rejects_explicit_null(client: TestClient) -> None:
    client.post("/tasks", json={"title": "Keep a title"})
    response = client.patch("/tasks/1", json={"title": None})
    assert response.status_code == 422
