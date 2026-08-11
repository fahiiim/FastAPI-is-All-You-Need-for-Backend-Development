from collections.abc import Generator

import pytest
from app.database.models import Base
from app.database.session import get_session
from app.main import app
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
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def register_and_login(client: TestClient, email: str) -> str:
    password = "correct horse battery staple"
    registered = client.post(
        "/v1/auth/register", json={"email": email, "password": password}
    )
    assert registered.status_code == 201
    logged_in = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert logged_in.status_code == 200
    return logged_in.json()["access_token"]


def test_authentication_and_resource_authorization(client: TestClient) -> None:
    owner_token = register_and_login(client, "owner@example.com")
    other_token = register_and_login(client, "other@example.com")

    unauthenticated = client.post("/v1/projects", json={"name": "Private"})
    assert unauthenticated.status_code == 401

    created = client.post(
        "/v1/projects",
        json={"name": "Private"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    hidden = client.get(
        f"/v1/projects/{project_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert hidden.status_code == 404

    visible = client.get(
        f"/v1/projects/{project_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert visible.status_code == 200
    assert visible.json()["name"] == "Private"


def test_duplicate_project_is_a_stable_conflict(client: TestClient) -> None:
    token = register_and_login(client, "duplicate@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/v1/projects", json={"name": "One"}, headers=headers).status_code == 201

    duplicate = client.post("/v1/projects", json={"name": "One"}, headers=headers)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"
