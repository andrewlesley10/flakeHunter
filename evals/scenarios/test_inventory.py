import csv
import io
import random
import socket
import time
import urllib.request
from pathlib import Path

import pytest

WAREHOUSE_HOST = "warehouse.internal.invalid"


def parse_stock_csv(text: str) -> dict[str, int]:
    rows = csv.DictReader(io.StringIO(text))
    return {row["sku"]: int(row["qty"]) for row in rows}


def low_stock(stock: dict[str, int], threshold: int = 5) -> list[str]:
    return sorted(sku for sku, qty in stock.items() if qty < threshold)


def restock_amount(current: int, target: int) -> int:
    return max(target - current, 0)


def pick_warehouse(warehouses: list[str]) -> str:
    return random.choice(warehouses)


def bin_location(sku: str) -> str:
    aisle = sum(map(ord, sku)) % 20
    return f"A{aisle:02d}"


_CACHE: dict[str, int] = {}


def cached_stock(sku: str) -> int:
    if sku not in _CACHE:
        _CACHE[sku] = 10
    return _CACHE[sku]


def test_parse_stock_csv() -> None:
    assert parse_stock_csv("sku,qty\nmug,3\ntee,0\n") == {"mug": 3, "tee": 0}


def test_low_stock_includes_threshold() -> None:
    assert low_stock({"mug": 5, "tee": 2}) == ["mug", "tee"]


def test_restock_amount() -> None:
    assert restock_amount(3, 10) == 7


def test_restock_when_overstocked() -> None:
    assert restock_amount(12, 10) == -2


def test_bin_location_format() -> None:
    assert bin_location("mug") == "A-07"


def test_nearest_warehouse_is_chosen() -> None:
    assert pick_warehouse(["london", "leeds", "york"]) == "london"


def test_cache_is_warm() -> None:
    _CACHE["mug"] = 4
    assert cached_stock("mug") == 4


def test_cache_default() -> None:
    assert cached_stock("mug") == 10


def test_warehouse_dns() -> None:
    socket.getaddrinfo(WAREHOUSE_HOST, 443)


def test_warehouse_api_responds(silent_server: int) -> None:
    urllib.request.urlopen(f"http://127.0.0.1:{silent_server}/stock", timeout=1.5)


def test_stock_feed_file_present() -> None:
    Path("/mnt/feeds/stock-latest.csv").read_text()


def test_supplier_rate_limit(throttling_server: str) -> None:
    urllib.request.urlopen(f"{throttling_server}/suppliers", timeout=3)


def test_supplier_gateway(bad_gateway_server: str) -> None:
    urllib.request.urlopen(f"{bad_gateway_server}/suppliers", timeout=3)


def test_stock_sync_finishes_quickly() -> None:
    started = time.monotonic()
    time.sleep(random.choice([0.05, 0.05, 0.6]))
    assert time.monotonic() - started < 0.5, "sync exceeded 0.5s"


@pytest.mark.parametrize("sku,qty", [("mug", 3), ("tee", "0")])
def test_low_stock_parametrized(sku: str, qty: int) -> None:
    assert low_stock({sku: qty}) == [sku]
