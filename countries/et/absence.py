"""Absence deductions on a 30-day company month.

basic deduction     = basic / divisor x unpaid days (absent, unpaid leave, half day = 0.5)
transport deduction = transport / divisor x (unpaid days + paid-leave days)
                      so both absence and paid leave reduce the transport allowance.

A date is counted once even if several records exist for it. Deductions never exceed the
amount they come from.

No Django imports.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import NamedTuple

from core.money import D, money

ABSENT = "absent"
UNPAID_LEAVE = "unpaid_leave"
HALF_DAY = "half_day"
UNPAID_FULL_STATUSES = frozenset({ABSENT, UNPAID_LEAVE})
PAID_LEAVE_STATUSES = frozenset(
    {
        "annual_leave",
        "sick_leave",
        "maternity_leave",
        "paternity_leave",
        "special_leave",
        "other_approved_leave",
    }
)


class DayRecord(NamedTuple):
    day: date
    status: str


@dataclass(frozen=True)
class AbsenceResult:
    unpaid_days: Decimal
    leave_transport_days: Decimal
    basic_deduction: Decimal
    transport_deduction: Decimal
    dates: list[date] = field(default_factory=list)

    @property
    def transport_days(self) -> Decimal:
        return self.unpaid_days + self.leave_transport_days


def daily_rate(monthly_amount, divisor=30) -> Decimal:
    divisor = D(divisor)
    if divisor <= 0:
        raise ValueError("The absence divisor must be greater than zero")
    return money(D(monthly_amount) / divisor)


def compute_absence(
    records: Iterable[DayRecord], basic_salary, transport_allowance, divisor=30
) -> AbsenceResult:
    by_day: dict[date, set[str]] = {}
    for record in records:
        by_day.setdefault(record.day, set()).add(record.status)

    unpaid = Decimal("0")
    leave_days = Decimal("0")
    touched: list[date] = []
    for day in sorted(by_day):
        statuses = by_day[day]
        if statuses & UNPAID_FULL_STATUSES:
            unpaid += 1
        elif HALF_DAY in statuses:
            unpaid += Decimal("0.5")
        elif statuses & PAID_LEAVE_STATUSES:
            leave_days += 1
        else:
            continue
        touched.append(day)

    basic_deduction = min(money(daily_rate(basic_salary, divisor) * unpaid), money(basic_salary))
    transport_deduction = min(
        money(daily_rate(transport_allowance, divisor) * (unpaid + leave_days)),
        money(transport_allowance),
    )
    return AbsenceResult(unpaid, leave_days, basic_deduction, transport_deduction, touched)
