from unittest.mock import Mock

import httpx
import pytest

from app import main


def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_login(client, passwords) -> None:
    response = client.post("/auth/login", json={"username": "admin", "password": passwords["admin"]})
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_wrong_password(client) -> None:
    assert client.post("/auth/login", json={"username": "admin", "password": "incorrect"}).status_code == 401


def test_missing_password(client) -> None:
    assert client.post("/auth/login", json={"username": "admin"}).status_code == 422


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer invalid"}], ids=["missing", "invalid"])
def test_requires_valid_token(client, headers) -> None:
    assert client.get("/bikes", headers=headers).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("POST", "/bikes", {"name": "X", "price": 1}), ("PUT", "/bikes/1", {"name": "X", "price": 1, "in_stock": 0}),
     ("PATCH", "/bikes/1", {"name": "X"}), ("DELETE", "/bikes/1", None), ("POST", "/bikes/1/stock", {"delta": 1})],
    ids=["post", "put", "patch", "delete", "stock"],
)
def test_viewer_cannot_write(client, viewer_headers, method, path, body) -> None:
    assert client.request(method, path, headers=viewer_headers, json=body).status_code == 403


def test_create_defaults(client, admin_headers) -> None:
    response = client.post("/bikes", json={"name": "City", "price": 7}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json() == {"id": 1, "name": "City", "price": 7.0, "in_stock": 0}


def test_viewer_gets_one(client, viewer_headers, make_item) -> None:
    bike = make_item()
    result = client.get(f"/bikes/{bike['id']}", headers=viewer_headers)
    assert result.status_code == 200
    assert result.json() == bike


def test_list_sorted_by_id(client, viewer_headers, make_item) -> None:
    first, second = make_item("B"), make_item("A")
    assert client.get("/bikes", headers=viewer_headers).json() == [first, second]


def test_put_replaces_all_fields(client, admin_headers, make_item) -> None:
    bike = make_item()
    body = {"name": "Road", "price": 9, "in_stock": 11}
    response = client.put(f"/bikes/{bike['id']}", json=body, headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == {**body, "id": bike["id"]}


def test_patch_preserves_other_fields(client, admin_headers, make_item) -> None:
    bike = make_item()
    response = client.patch(f"/bikes/{bike['id']}", json={"price": 88}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == {**bike, "price": 88}


def test_delete_then_get(client, admin_headers, make_item) -> None:
    path = f"/bikes/{make_item()['id']}"
    response = client.delete(path, headers=admin_headers)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get(path, headers=admin_headers).status_code == 404


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [("GET", "", None), ("PUT", "", {"name": "X", "price": 2, "in_stock": 0}),
     ("PATCH", "", {"price": 3}), ("DELETE", "", None), ("POST", "/stock", {"delta": 1})],
    ids=["get", "put", "patch", "delete", "stock"],
)
def test_missing_bike(client, admin_headers, method, suffix, body) -> None:
    assert client.request(method, "/bikes/999" + suffix, headers=admin_headers, json=body).status_code == 404


@pytest.mark.parametrize(
    "overrides",
    [{"name": ""}, {"name": " "}, {"name": "X"*101}, {"price": 0}, {"price": -1}, {"price": "free"},
     {"in_stock": -1}, {"in_stock": 26}, {"in_stock": 1.5}],
    ids=["empty", "blank", "long", "zero-price", "negative-price", "price-type", "negative-stock", "limit", "fraction"],
)
def test_invalid_create(client, admin_headers, overrides) -> None:
    response = client.post("/bikes", headers=admin_headers, json={"name": "City", "price": 50, **overrides})
    assert response.status_code == 422


@pytest.mark.parametrize("body", [{}, {"price": None}], ids=["empty", "null"])
def test_invalid_patch(client, admin_headers, make_item, body) -> None:
    bike = make_item()
    assert client.patch(f"/bikes/{bike['id']}", headers=admin_headers, json=body).status_code == 422


def test_duplicate_name(client, admin_headers, make_item) -> None:
    make_item("City")
    assert client.post("/bikes", headers=admin_headers, json={"name": "City", "price": 1}).status_code == 409


def test_stock_can_reach_both_boundaries(client, admin_headers, make_item) -> None:
    bike = make_item(in_stock=0)
    path = f"/bikes/{bike['id']}/stock"
    for delta, expected in [(25, 25), (-25, 0)]:
        response = client.post(path, json={"delta": delta}, headers=admin_headers)
        assert response.status_code == 200
        assert response.json()["in_stock"] == expected


@pytest.mark.parametrize("delta", [-3, 24, 100], ids=["below-zero", "above-limit", "large"])
def test_stock_conflict_preserves_balance(client, admin_headers, make_item, delta) -> None:
    bike = make_item(in_stock=2)
    path = f"/bikes/{bike['id']}"
    assert client.post(path + "/stock", json={"delta": delta}, headers=admin_headers).status_code == 409
    assert client.get(path, headers=admin_headers).json()["in_stock"] == 2


def test_zero_delta_rejected(client, admin_headers, make_item) -> None:
    bike = make_item()
    assert client.post(f"/bikes/{bike['id']}/stock", json={"delta": 0}, headers=admin_headers).status_code == 422


def test_unicode_substring(client, viewer_headers, make_item) -> None:
    target = make_item("Городской")
    make_item("Шоссе")
    assert client.get("/bikes", params={"q": "РОДС"}, headers=viewer_headers).json() == [target]


def test_inclusive_prices(client, viewer_headers, make_item) -> None:
    make_item("A", 5)
    included = [make_item("B", 10), make_item("C", 20)]
    make_item("D", 25)
    result = client.get("/bikes", params={"min_price": 10, "max_price": 20}, headers=viewer_headers)
    assert result.json() == included


def test_pagination(client, viewer_headers, make_item) -> None:
    make_item("A")
    middle = make_item("B")
    make_item("C")
    assert client.get("/bikes", params={"limit": 1, "offset": 1}, headers=viewer_headers).json() == [middle]


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}, {"min_price": 10, "max_price": 1}])
def test_invalid_filters(client, viewer_headers, params) -> None:
    assert client.get("/bikes", params=params, headers=viewer_headers).status_code == 422


def test_currency_conversion(client, viewer_headers, make_item) -> None:
    bike = make_item(price=200)
    rates = Mock(return_value=0.0125)
    main.app.dependency_overrides[main.get_rate_source] = lambda: rates
    result = client.get(f"/bikes/{bike['id']}/price", params={"currency": "USD"}, headers=viewer_headers)
    assert result.status_code == 200
    assert result.json() == {"currency": "USD", "price": 2.5}
    rates.assert_called_once_with("USD")


def test_unavailable_rate_service(client, viewer_headers, make_item, monkeypatch) -> None:
    bike = make_item()
    monkeypatch.setenv("BIKES_RATES_URL", "http://rates.test/rates")
    transport = Mock(side_effect=httpx.ConnectError("offline"))
    monkeypatch.setattr(main.httpx, "get", transport)
    response = client.get(f"/bikes/{bike['id']}/price", params={"currency": "EUR"}, headers=viewer_headers)
    assert response.status_code == 502
    transport.assert_called_once_with("http://rates.test/rates", timeout=3)


def test_unknown_currency(client, viewer_headers, make_item) -> None:
    bike = make_item()
    assert client.get(f"/bikes/{bike['id']}/price?currency=GBP", headers=viewer_headers).status_code == 422


def test_deletion_does_not_reuse_an_existing_id(client, admin_headers, make_item) -> None:
    first, second = make_item("A"), make_item("B")
    client.delete(f"/bikes/{first['id']}", headers=admin_headers)
    third = make_item("C")
    assert third["id"] != second["id"]
    assert client.get(f"/bikes/{second['id']}", headers=admin_headers).json() == second
