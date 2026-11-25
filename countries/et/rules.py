"""The pay rules in force for one client: Ethiopian defaults plus the client's overrides.

No Django imports.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from typing import Any

from .pension import EMPLOYEE_RATE, EMPLOYER_RATE
from .tax import Bracket


@dataclass(frozen=True)
class PayRules:
    absence_divisor: int = 30
    pension_employee_rate: Decimal = EMPLOYEE_RATE
    pension_employer_rate: Decimal = EMPLOYER_RATE
    pension_min_days: int = 10
    # Overtime and attendance rules, used by modules built later.
    ot_days: int = 30
    ot_hours_per_day: int = 8
    weekly_rest_day: int = 6  # Python weekday number: Monday 0 ... Sunday 6
    # What counts as taxable income. Check each against the client's own tax advice.
    ot_taxable: bool = True
    transport_taxable: bool = True
    bonus_taxable: bool = True
    # Part-month pay. New hires are always paid from their hire date; these two decide the
    # rest. Off keeps the old behaviour: leavers get the full month, allowances are not cut.
    prorate_leavers: bool = False
    prorate_allowances: bool = False


_NAMES = {field.name for field in fields(PayRules)}


def resolve_rules(overrides: Mapping[str, Any] | None = None) -> PayRules:
    """Ethiopian defaults with the client's ``[rules]`` overrides applied."""
    overrides = dict(overrides or {})
    unknown = sorted(set(overrides) - _NAMES)
    if unknown:
        raise ValueError(f"Unknown pay rule(s): {', '.join(unknown)}")
    return PayRules(**overrides)


def rules_snapshot(rules: PayRules, brackets: tuple[Bracket, ...]) -> dict:
    """Everything a payroll run was calculated with, as plain text and numbers.

    Stored with each run so the figures can always be explained later, even after the rules
    or the tax schedule change.
    """
    values = {
        key: str(value) if isinstance(value, Decimal) else value
        for key, value in asdict(rules).items()
    }
    values["tax_brackets"] = [
        {
            "min_income": str(band.min_income),
            "max_income": None if band.max_income is None else str(band.max_income),
            "rate": str(band.rate),
            "quick_deduction": str(band.quick_deduction),
        }
        for band in brackets
    ]
    return values
