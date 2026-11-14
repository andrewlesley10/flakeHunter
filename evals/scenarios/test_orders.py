import random
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

TAX_RATE = 0.2


@dataclass
class Order:
    lines: list[tuple[str, float, int]] = field(default_factory=list)
    coupon: str | None = None


def subtotal(order: Order) -> float:
    return sum(price for _, price, qty in order.lines)


def order_total(order: Order) -> float:
    base = sum(price * qty for _, price, qty in order.lines)
    if order.coupon == "HALF":
        base = base / 2
    return round(base * (1 + TAX_RATE), 2)


def delivery_date(ordered: date, express: bool) -> date:
    days = 1 if express else 5
    current = ordered
    while days:
        current += timedelta(days=1)
        if current.weekday() < 6:
            days -= 1
    return current


def split_payment(total: float, people: int) -> list[float]:
    share = round(total / people, 2)
    return [share] * people


def reserve_stock(stock: dict[str, int], sku: str, qty: int) -> dict[str, int]:
    stock[sku] = stock.get(sku, 0) - qty
    return stock


_ORDER_IDS: list[int] = []


def next_order_id() -> int:
    _ORDER_IDS.append(len(_ORDER_IDS) + 1)
    return _ORDER_IDS[-1]


def test_subtotal_counts_quantities() -> None:
    order = Order(lines=[("mug", 12.0, 2), ("tee", 20.0, 1)])
    assert subtotal(order) == 44.0


def test_total_includes_tax() -> None:
    order = Order(lines=[("mug", 10.0, 1)])
    assert order_total(order) == 12.0


def test_half_coupon() -> None:
    order = Order(lines=[("mug", 10.0, 2)], coupon="HALF")
    assert order_total(order) == 10.0


def test_express_delivery_skips_weekend() -> None:
    friday = date(2026, 11, 13)
    assert delivery_date(friday, express=True) == date(2026, 11, 16)


def test_split_payment_adds_up() -> None:
    shares = split_payment(100.0, 3)
    assert sum(shares) == 100.0


def test_reserve_stock_never_negative() -> None:
    stock = reserve_stock({"mug": 1}, "mug", 3)
    assert stock["mug"] >= 0, f"stock went negative: {stock}"


def test_order_ids_start_at_one() -> None:
    assert next_order_id() == 1


def test_order_ids_are_sequential() -> None:
    first = next_order_id()
    assert first == 1


def test_random_sample_of_orders_is_valid() -> None:
    orders = [Order(lines=[("mug", 12.0, random.randint(0, 3))]) for _ in range(3)]
    assert all(order_total(o) > 0 for o in orders)


def test_order_created_within_second() -> None:
    started = time.time()
    time.sleep(random.uniform(0.0, 0.3))
    assert time.time() - started < 0.15


def test_total_rounding() -> None:
    order = Order(lines=[("pen", 0.1, 3)])
    assert order_total(order) == 0.37
