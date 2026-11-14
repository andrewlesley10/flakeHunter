"""Pricing rules for the demo shop."""

DISCOUNT_CODES = {"SAVE10": 10, "SAVE25": 25}


def apply_discount(subtotal: float, code: str | None) -> float:
    """Return the total after a percentage discount code, rounded to cents."""
    percent = DISCOUNT_CODES.get(code or "", 0)
    return round(subtotal * (100 - percent) / 100, 2)
