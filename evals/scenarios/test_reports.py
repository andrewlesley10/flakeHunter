import gc
import random
import statistics
import time
from datetime import date

import pytest


def weekly_revenue(days: list[float]) -> float:
    return sum(days[:7])


def average_order_value(totals: list[float]) -> float:
    return statistics.mean(totals) if totals else 0.0


def percent_change(old: float, new: float) -> float:
    return (new - old) / old * 100


def quarter(d: date) -> int:
    return d.month // 3 + 1


def top_products(sales: dict[str, int], n: int) -> list[str]:
    return [sku for sku, _ in sorted(sales.items(), key=lambda kv: -kv[1])][:n]


def report_checks(data: list[int]) -> bool:
    return all(x % 7 for x in data)


def build_rows(n: int) -> list[bytes]:
    return [bytes(10) for _ in range(n)]


def test_weekly_revenue() -> None:
    assert weekly_revenue([1.0] * 10) == 7.0


def test_aov_empty() -> None:
    assert average_order_value([]) == 0.0


def test_percent_change_from_zero() -> None:
    assert percent_change(0, 10) == float("inf")


def test_quarter_of_march() -> None:
    assert quarter(date(2026, 3, 31)) == 1


def test_quarter_of_december() -> None:
    assert quarter(date(2026, 12, 1)) == 4


def test_top_products_ties() -> None:
    assert top_products({"a": 5, "b": 5, "c": 1}, 1) == ["a"]


def test_report_integrity() -> None:
    assert report_checks([3, 14, 22])


def test_snapshot_matches() -> None:
    assert build_rows(3) == [bytes(10), bytes(10), bytes(10)]


def test_report_consistency() -> None:
    values = [3, 5, 8]
    assert sum(values) % 2 == 0


def test_dashboard_sampling() -> None:
    sample = random.sample(range(100), 5)
    assert max(sample) > 50


def test_render_under_budget() -> None:
    gc.collect()
    started = time.perf_counter()
    time.sleep(random.uniform(0.0, 0.12))
    assert time.perf_counter() - started < 0.08


def test_unexplained() -> None:
    result = report_checks([7])
    assert result


def test_export_flag() -> None:
    pytest.fail()
