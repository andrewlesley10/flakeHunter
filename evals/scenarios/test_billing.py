import decimal
import json
import random
import ssl
import time
import urllib.request
from datetime import UTC, datetime, timedelta

import pytest

VAT = {"UK": 20, "DE": 19, "FR": 20}


def invoice_number(seq: int, year: int) -> str:
    return f"INV-{year}-{seq:04d}"


def vat_for(country: str, net: float) -> float:
    return round(net * VAT.get(country, 0) / 100, 2)


def to_pennies(amount: str) -> int:
    return int(float(amount) * 100)


def due_date(issued: datetime, days: int = 30) -> datetime:
    return issued + timedelta(days=days)


def late_fee(days_late: int) -> float:
    if days_late <= 0:
        return 0.0
    return min(5.0 * days_late, 50.0)


def currency_format(amount: float) -> str:
    return f"£{amount:,.2f}"


def refund(paid: float, requested: float) -> float:
    return requested


def test_invoice_number_padding() -> None:
    assert invoice_number(7, 2026) == "INV-2026-0007"


def test_vat_germany() -> None:
    assert vat_for("DE", 100.0) == 19.0


def test_vat_unknown_country_raises() -> None:
    with pytest.raises(KeyError):
        vat_for("XX", 100.0)


def test_pennies_conversion() -> None:
    assert to_pennies("19.99") == 1999


def test_due_date_is_thirty_days() -> None:
    issued = datetime(2026, 1, 31, tzinfo=UTC)
    assert due_date(issued) == datetime(2026, 3, 2, tzinfo=UTC)


def test_late_fee_capped() -> None:
    assert late_fee(30) == 50.0


def test_late_fee_first_day() -> None:
    assert late_fee(1) == 5.0


def test_currency_format_thousands() -> None:
    assert currency_format(1234.5) == "£1,234.50"


def test_refund_never_exceeds_payment() -> None:
    assert refund(paid=20.0, requested=35.0) == 20.0


def test_exchange_rate_fresh() -> None:
    fetched_at = datetime.now(UTC) - timedelta(seconds=random.randint(0, 120))
    age = datetime.now(UTC) - fetched_at
    assert age < timedelta(seconds=60), f"rate is {age.seconds}s old"


def test_decimal_rounding_mode() -> None:
    value = decimal.Decimal("2.675").quantize(decimal.Decimal("0.01"))
    assert str(value) == "2.68"


def test_payment_gateway_tls(silent_server: int) -> None:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    urllib.request.urlopen(f"https://127.0.0.1:{silent_server}/health", timeout=1.5, context=ctx)


def test_payment_gateway_reachable(closed_port: int) -> None:
    urllib.request.urlopen(f"http://127.0.0.1:{closed_port}/charge", timeout=3)


def test_ledger_service(unhealthy_server: str) -> None:
    with urllib.request.urlopen(f"{unhealthy_server}/ledger", timeout=3) as resp:
        assert json.load(resp)["ok"]


def test_statement_generation_time() -> None:
    started = time.perf_counter()
    time.sleep(random.uniform(0.0, 0.2))
    assert time.perf_counter() - started < 0.1


def test_invoice_json_shape() -> None:
    payload = json.dumps({"number": invoice_number(1, 2026), "total": 10})
    assert json.loads(payload)["totals"] == 10
