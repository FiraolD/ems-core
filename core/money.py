"""Money and rate arithmetic. Everything is Decimal; amounts are rounded half-up to 0.01.

No Django imports.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
RATE_QUANT = Decimal("0.0001")
ZERO = Decimal("0")


def D(value) -> Decimal:
    """Convert to Decimal. None and blank mean zero; thousands commas are accepted.

    Floats go through ``str`` so 2000.01 means exactly 2000.01, not its binary neighbour.
    """
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    text = str(value).strip().replace(",", "")
    if text == "":
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Not a number: {value!r}") from exc


def money(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def rate(value) -> Decimal:
    return D(value).quantize(RATE_QUANT, rounding=ROUND_HALF_UP)
