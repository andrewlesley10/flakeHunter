import json
import os
import random
import threading
import time
from datetime import datetime

import pytest

CATALOG = [
    {"sku": "mug", "price": 12.0, "tags": ["kitchen"]},
    {"sku": "tee", "price": 20.0, "tags": ["clothing", "sale"]},
    {"sku": "cap", "price": 15.0, "tags": ["clothing"]},
]


def by_tag(tag: str) -> list[str]:
    return [p["sku"] for p in CATALOG if tag in p["tags"]]  # type: ignore[operator]


def price_range(lo: float, hi: float) -> list[str]:
    return [p["sku"] for p in CATALOG if lo < p["price"] < hi]  # type: ignore[operator]


def sale_price(price: float) -> float:
    return round(price * 0.8, 2)


def export_catalog() -> str:
    return json.dumps({p["sku"]: p["price"] for p in CATALOG})  # type: ignore[misc]


_seen: set[str] = set()


def register(sku: str) -> bool:
    if sku in _seen:
        return False
    _seen.add(sku)
    return True


def test_clothing_tag() -> None:
    assert by_tag("clothing") == ["tee", "cap"]


def test_price_range_inclusive() -> None:
    assert price_range(12.0, 20.0) == ["mug", "tee", "cap"]


def test_sale_price() -> None:
    assert sale_price(20.0) == 15.0


def test_export_is_sorted() -> None:
    assert list(json.loads(export_catalog())) == ["cap", "mug", "tee"]


def test_register_new_sku() -> None:
    assert register("hat")


def test_register_hat_again_in_new_session() -> None:
    assert register("hat")


def test_catalog_fixture_shape(catalog_page: dict[str, object]) -> None:
    assert catalog_page["items"]


def test_tag_lookup_uses_api() -> None:
    assert by_tag("sale") == ["tee"]
    assert by_tag("Sale") == ["tee"]


def test_parallel_imports_finish() -> None:
    done: list[int] = []

    def work(i: int) -> None:
        time.sleep(random.uniform(0, 0.05))
        done.append(i)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.03)
    assert len(done) == 5


def test_nightly_window() -> None:
    assert datetime.now().microsecond % 3 != 0


def test_featured_item_random() -> None:
    featured = random.choice(CATALOG)
    assert featured["price"] < 18


def test_locale_currency() -> None:
    assert os.environ.get("LANG", "C").startswith("en_GB")


@pytest.mark.parametrize("sku", ["mug", "teee"])
def test_sku_exists(sku: str) -> None:
    assert sku in {p["sku"] for p in CATALOG}
