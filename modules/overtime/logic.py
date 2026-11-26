"""Overtime rules and pay arithmetic. No Django imports.

Pay = hourly rate x sum(hours x multiplier), where hourly rate = monthly basic salary divided by
(ot_days x ot_hours_per_day) from the pay rules (30 x 8 = 240 by default).

Each entry has a category kind that must match the day it was worked on, so a public holiday or
rest day can never be recorded at the ordinary rate by mistake.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation

from core.money import D, money

NORMAL = "normal"        # ordinary working day, daytime
NIGHT = "night"          # ordinary working day, night hours
REST_DAY = "rest_day"    # the weekly rest day
HOLIDAY = "public_holiday"
KINDS = (NORMAL, NIGHT, REST_DAY, HOLIDAY)

MAX_HOURS_PER_ENTRY = Decimal("16")


class OvertimeError(ValueError):
    """The overtime cannot be recorded. The message is safe to show."""


def required_kind(day: date, *, rest_day: int, holidays=frozenset()) -> str | None:
    """The kind this day forces (holiday, then rest day), or None when normal or night both fit."""
    if day in holidays:
        return HOLIDAY
    if day.weekday() == rest_day:
        return REST_DAY
    return None


def validate_entry(kind: str, day: date, hours, *, rest_day: int, holidays=frozenset()) -> Decimal:
    try:
        hours = D(hours)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise OvertimeError("Hours must be a number.") from exc
    if not hours.is_finite() or hours <= 0:
        raise OvertimeError("Hours must be more than zero.")
    if hours > MAX_HOURS_PER_ENTRY:
        raise OvertimeError(f"One entry cannot be more than {MAX_HOURS_PER_ENTRY} hours. Split it by day.")
    forced = required_kind(day, rest_day=rest_day, holidays=holidays)
    if forced and kind != forced:
        label = "a public holiday" if forced == HOLIDAY else "the weekly rest day"
        raise OvertimeError(f"{day} is {label}, so it must be recorded in that category.")
    if not forced and kind in (REST_DAY, HOLIDAY):
        label = "a public holiday" if kind == HOLIDAY else "the weekly rest day"
        raise OvertimeError(f"{day} is not {label}.")
    return hours


def hourly_rate(monthly_basic, ot_days: int, ot_hours_per_day: int) -> Decimal:
    divisor = Decimal(ot_days) * Decimal(ot_hours_per_day)
    if divisor <= 0:
        raise ValueError("Overtime days and hours per day must be more than zero.")
    return D(monthly_basic) / divisor


def weighted_hours(entries: Iterable[tuple]) -> Decimal:
    """Sum of hours x multiplier over (hours, multiplier) pairs."""
    return sum((D(h) * D(m) for h, m in entries), Decimal("0"))


def overtime_pay(monthly_basic, entries: Iterable[tuple], ot_days: int, ot_hours_per_day: int) -> Decimal:
    """Money for the month, rounded once at the end so entries never accumulate rounding error."""
    return money(hourly_rate(monthly_basic, ot_days, ot_hours_per_day) * weighted_hours(entries))
