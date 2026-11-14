"""Pricing rules for the demo shop."""

DISCOUNT_CODES = {"SAVE10": 10, "SAVE25": 25}
FIXED_CODES = {"TENOFF": 10.0}


def apply_discount(subtotal: float, code: str | None) -> float:
    """Return the total after a discount code (percentage or fixed amount)."""
    if code in FIXED_CODES:
        return round(max(subtotal - FIXED_CODES[code], 0), 2)
    amount = DISCOUNT_CODES.get(code or "", 0)
    return round(max(subtotal - amount, 0), 2)
