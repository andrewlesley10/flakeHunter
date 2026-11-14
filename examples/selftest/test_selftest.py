"""Deliberately failing tests used by .github/workflows/flakehunter-selftest.yml.

Not part of the normal test suite (pytest's testpaths is "tests"). Each test fails in
a known way so the self-test PR comment can be checked by eye.
"""

import os
import socket


def apply_discount(price: float, percent: float) -> float:
    return price - price * percent / 10  # bug on purpose: should be / 100


def test_discount_is_ten_percent() -> None:  # product_bug
    assert apply_discount(100, 10) == 90


def test_inventory_service_reachable() -> None:  # environment
    socket.create_connection(("127.0.0.1", 9), timeout=2)


def test_cart_badge_updates() -> None:  # flaky: fails first time, passes on re-run
    marker = "/tmp/flakehunter-selftest-ran"
    first_run = not os.path.exists(marker)
    open(marker, "w").close()
    assert not first_run, "cart badge still showed 0 items"
