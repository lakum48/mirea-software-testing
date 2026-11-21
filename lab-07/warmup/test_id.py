from collections.abc import Iterator
from itertools import count

import pytest
from fastapi.testclient import TestClient

from warmup import app_v0


@pytest.fixture
def client_v0() -> Iterator[TestClient]:
    app_v0.ITEMS.clear()
    app_v0.sequence = count(1)
    with TestClient(app_v0.app) as client:
        yield client
    app_v0.ITEMS.clear()


def test_deletion_preserves_second_item(client_v0: TestClient) -> None:
    first = client_v0.post("/items", json={"name": "A", "price": 1}).json()["id"]
    second = client_v0.post("/items", json={"name": "B", "price": 2}).json()["id"]
    assert client_v0.delete(f"/items/{first}").status_code == 204

    third = client_v0.post("/items", json={"name": "C", "price": 3}).json()["id"]

    assert third != second
    assert app_v0.ITEMS[second] == {"name": "B", "price": 2}
