"""Turn the text an administrator types into a checked, typed rule value.

No Django imports.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from core.extensions.client import RULE_KEYS


class RuleValueError(ValueError):
    """The text is not a valid value for this rule."""


_TRUE = {"true", "yes", "1", "on"}
_FALSE = {"false", "no", "0", "off"}

LABELS = {
    "absence_divisor": "Days in the pay month (absence, new hires, pension proration)",
    "ot_days": "Days in the month for the overtime hourly rate",
    "ot_hours_per_day": "Working hours per day for the overtime hourly rate",
    "weekly_rest_day": "Weekly rest day (Monday 0 ... Sunday 6)",
    "pension_employee_rate": "Pension: employee rate (0.07 = 7%)",
    "pension_employer_rate": "Pension: employer rate (0.11 = 11%)",
    "pension_min_days": "Pension: minimum days of service in the hiring month",
    "ot_taxable": "Overtime is taxable income",
    "transport_taxable": "Transport allowance is taxable income",
    "bonus_taxable": "Bonus is taxable income",
    "prorate_leavers": "Pay people who leave mid-month only up to their leaving date",
    "prorate_allowances": "Also prorate allowances for part-month workers",
}


def rule_choices() -> list[tuple[str, str]]:
    return [(key, LABELS.get(key, key)) for key in RULE_KEYS]


def parse_rule_text(key: str, text: str) -> Any:
    """The typed value for ``key`` written as ``text``, or ``RuleValueError``."""
    if key not in RULE_KEYS:
        raise RuleValueError(f"Unknown rule {key!r}")
    kind, low, high = RULE_KEYS[key]
    raw = (text or "").strip()
    if not raw:
        raise RuleValueError("Enter a value")

    if kind == "bool":
        lowered = raw.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise RuleValueError("Enter yes or no")

    if kind == "int":
        try:
            number = int(raw)
        except ValueError:
            raise RuleValueError("Enter a whole number") from None
        if not low <= number <= high:
            raise RuleValueError(f"Enter a number between {low} and {high}")
        return number

    try:  # kind == "rate": a fraction, so 7% is written 0.07
        rate = Decimal(raw)
    except InvalidOperation:
        raise RuleValueError("Enter a decimal such as 0.07") from None
    if not rate.is_finite() or not 0 <= rate <= 1:
        raise RuleValueError("Enter a fraction between 0 and 1, for example 0.07 for 7%")
    return rate


def store_rule_value(value: Any) -> str:
    """The text form kept in the database. Round-trips through ``parse_rule_text``."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)
