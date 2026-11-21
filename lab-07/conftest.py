import secrets
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    main.Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            yield session
    finally:
        engine.dispose()


@pytest.fixture
def passwords(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    generated = {role: secrets.token_urlsafe(18) for role in ("admin", "viewer")}
    for role, value in generated.items():
        monkeypatch.setenv(f"BIKES_{role.upper()}_PASSWORD", value)
    return generated


@pytest.fixture
def client(db_session: Session, passwords: dict[str, str]) -> Iterator[TestClient]:
    main.app.dependency_overrides[main.db_session] = lambda: db_session
    client = TestClient(main.app)
    try:
        yield client
    finally:
        client.close()
        main.app.dependency_overrides.clear()
        main.tokens.clear()


def login_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def admin_headers(client: TestClient, passwords: dict[str, str]) -> dict[str, str]:
    return login_headers(client, "admin", passwords["admin"])


@pytest.fixture
def viewer_headers(client: TestClient, passwords: dict[str, str]) -> dict[str, str]:
    return login_headers(client, "viewer", passwords["viewer"])


@pytest.fixture
def make_item(client: TestClient, admin_headers: dict[str, str]) -> Callable:
    def create(name: str = "City", price: float = 500, in_stock: int = 2) -> dict:
        response = client.post("/bikes", headers=admin_headers, json={"name": name, "price": price, "in_stock": in_stock})
        assert response.status_code == 201, response.text
        return response.json()

    return create
