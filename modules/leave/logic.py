"""Leave rules: counting days, entitlement, balances. No Django imports.

Conventions (each is a policy a client may want different, so they are kept in one place):
- Leave counts working days: the weekly rest day and public holidays inside the range are free.
- A request stays inside one calendar year; leave over New Year is two requests.
- Years of service are the whole years completed on 1 January of the leave year.
- In the year someone joins, entitlement can be pro-rated by the months left (hire month counts).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

HALF = Decimal("0.5")


class LeaveError(ValueError):
    """The request cannot be counted or is not allowed. The message is safe to show."""


def count_leave_days(start: date, end: date, *, rest_day: int, holidays=frozenset(), half_day: bool = False) -> Decimal:
    if end < start:
        raise LeaveError("The end date is before the start date.")
    if start.year != end.year:
        raise LeaveError("A request must stay within one calendar year. Make a second request for the new year.")
    days = 0
    day = start
    while day <= end:
        if day.weekday() != rest_day and day not in holidays:
            days += 1
        day += timedelta(days=1)
    if half_day:
        if start != end:
            raise LeaveError("A half day must be a single day.")
        if days == 0:
            raise LeaveError("That day is a rest day or public holiday, so no leave is needed.")
        return HALF
    if days == 0:
        raise LeaveError("Every day in that range is a rest day or public holiday, so no leave is needed.")
    return Decimal(days)


def service_years(hire_date: date, on: date) -> int:
    years = on.year - hire_date.year - ((on.month, on.day) < (hire_date.month, hire_date.day))
    return max(years, 0)


def _to_half_day(value: Decimal) -> Decimal:
    return (value * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2


def entitlement(base_days: Decimal, extra_day_every_years: int, hire_date: date, year: int,
                *, prorate_first_year: bool = True) -> Decimal:
    """Days earned for a leave year. 0 before the hire year."""
    if year < hire_date.year:
        return Decimal("0")
    years = service_years(hire_date, date(year, 1, 1))
    extra = (years // extra_day_every_years) if extra_day_every_years > 0 else 0
    full = Decimal(base_days) + Decimal(extra)
    if year == hire_date.year and prorate_first_year:
        months_left = 12 - hire_date.month + 1
        return _to_half_day(full * Decimal(months_left) / Decimal(12))
    return full


@dataclass(frozen=True)
class Balance:
    year: int
    entitled: Decimal
    carried_in: Decimal
    adjustments: Decimal
    used: Decimal

    @property
    def remaining(self) -> Decimal:
        return self.entitled + self.carried_in + self.adjustments - self.used


def balance_for(year: int, *, base_days, extra_day_every_years: int, hire_date: date,
                used_by_year: dict[int, Decimal], adjustments_by_year: dict[int, Decimal],
                carry_over_max=Decimal("0"), prorate_first_year: bool = True) -> Balance:
    """Walk forward from the hire year so carried-over days are worked out correctly."""
    carry = Decimal("0")
    result = None
    for y in range(hire_date.year, year + 1):
        entitled = entitlement(Decimal(base_days), extra_day_every_years, hire_date, y,
                               prorate_first_year=prorate_first_year)
        adj = Decimal(adjustments_by_year.get(y, 0))
        used = Decimal(used_by_year.get(y, 0))
        result = Balance(y, entitled, carry, adj, used)
        carry = min(max(result.remaining, Decimal("0")), Decimal(carry_over_max))
    if result is None:  # a year before the hire year
        return Balance(year, Decimal("0"), Decimal("0"), Decimal(adjustments_by_year.get(year, 0)),
                       Decimal(used_by_year.get(year, 0)))
    return result


def overlaps(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    return a_start <= b_end and b_start <= a_end
