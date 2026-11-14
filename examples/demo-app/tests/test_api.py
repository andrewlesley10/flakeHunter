"""API tests for the demo shop.

Some of these fail on purpose in CI; EXPECTED.md lists which and why. Test names are
neutral so the model can't classify a failure from its name alone.
"""

import time

from fastapi.testclient import TestClient


def test_items_are_listed(client: TestClient) -> None:
    assert set(client.get("/items").json()) == {"mug", "tee", "cap"}


def test_cart_total_without_discount(client: TestClient) -> None:
    resp = client.post("/cart/total", json={"lines": [{"sku": "mug", "qty": 2}]})
    assert resp.json() == {"subtotal": 24.0, "total": 24.0}


def test_cart_total_with_discount(client: TestClient) -> None:
    cart = {"lines": [{"sku": "tee", "qty": 1}], "discount_code": "SAVE10"}
    assert client.post("/cart/total", json=cart).json()["total"] == 18.0


def test_unknown_sku_is_404(client: TestClient) -> None:
    resp = client.post("/cart/total", json={"lines": [{"sku": "hat", "qty": 1}]})
    assert resp.status_code == 404


def test_stock_lookup_is_fast(client: TestClient) -> None:
    start = time.monotonic()
    assert client.get("/stock/mug").json()["in_stock"] is True
    elapsed = time.monotonic() - start
    assert elapsed < 0.4, f"stock lookup took {elapsed:.2f}s (budget 0.4s)"


def test_checkout_charges_card(client: TestClient) -> None:
    cart = {"lines": [{"sku": "cap", "qty": 1}]}
    assert client.post("/checkout", json=cart).json() == {"status": "paid", "total": 15.0}


def test_fixed_amount_code(client: TestClient) -> None:
    cart = {"lines": [{"sku": "tee", "qty": 1}], "discount_code": "TENOFF"}
    assert client.post("/cart/total", json=cart).json()["total"] == 10.0


def test_discount_for_members(member_client: TestClient) -> None:
    cart = {"lines": [{"sku": "mug", "qty": 1}], "discount_code": "SAVE25"}
    assert member_client.post("/cart/total", json=cart).json()["total"] == 9.0
