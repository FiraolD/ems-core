"""Ethiopian private-organisation pension: employee 7% and employer 11% of pensionable pay.

Continuing staff: pensionable pay is basic salary after the unpaid-absence deduction.
Someone hired during the payroll month:
  - fewer than ``min_days`` calendar days of service through month end: no contribution;
  - ``min_days`` or more: pensionable pay = basic x service days / divisor.
The employer's share is a company cost and is never deducted from the employee.

No Django imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from core.money import D, money

EMPLOYEE_RATE = Decimal("0.07")
EMPLOYER_RATE = Decimal("0.11")


@dataclass(frozen=True)
class PensionResult:
    pensionable_salary: Decimal
    employee_rate: Decimal
    employer_rate: Decimal
    employee_contribution: Decimal
    employer_contribution: Decimal


@dataclass(frozen=True)
class PensionBase:
    pensionable: Decimal
    service_days: int | None  # only set for someone hired during the month
    prorated: bool


def calculate_pension(
    pensionable_salary, employee_rate=EMPLOYEE_RATE, employer_rate=EMPLOYER_RATE
) -> PensionResult:
    base = max(money(pensionable_salary), money(0))
    ee_rate, er_rate = D(employee_rate), D(employer_rate)
    return PensionResult(
        pensionable_salary=base,
        employee_rate=ee_rate,
        employer_rate=er_rate,
        employee_contribution=money(base * ee_rate),
        employer_contribution=money(base * er_rate),
    )


def service_days(hire_date: date, period_start: date, period_end: date) -> int:
    """Calendar days worked in the period, counting the hire day itself."""
    start = max(hire_date, period_start)
    return 0 if start > period_end else (period_end - start).days + 1


def pension_base(
    basic_salary,
    hire_date: date | None,
    period_start: date,
    period_end: date,
    absence_deduction=0,
    min_days: int = 10,
    divisor: int = 30,
) -> PensionBase:
    basic = money(basic_salary)
    if hire_date and period_start < hire_date <= period_end:
        days = service_days(hire_date, period_start, period_end)
        if days < min_days:
            return PensionBase(money(0), days, True)
        prorated = min(money(basic * D(days) / D(divisor)), basic)
        return PensionBase(prorated, days, True)
    earned = max(basic - money(absence_deduction), money(0))
    return PensionBase(earned, None, False)
