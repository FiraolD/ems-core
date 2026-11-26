"""Stops records that feed a locked payroll month from being changed.

Attendance, leave and overtime for a month whose payroll is locked can no longer affect pay, so
changing them would leave the records disagreeing with the payslips. The payroll module registers
a guard saying which dates are locked; modules ask here before changing anything dated in the past.

No Django imports.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date

_guards: list[Callable[[date], bool]] = []


class PeriodClosed(Exception):
    """The month's payroll is locked. The message is safe to show the user."""


def register(guard: Callable[[date], bool]) -> None:
    if guard not in _guards:
        _guards.append(guard)


def is_closed(day: date) -> bool:
    return any(guard(day) for guard in _guards)


def ensure_open(day: date, what: str = "This") -> None:
    if is_closed(day):
        raise PeriodClosed(
            f"The {day:%B %Y} payroll is locked, so {what.lower()} can no longer be changed. "
            "Ask the payroll administrator how to handle a correction."
        )


def ensure_open_range(start: date, end: date, what: str = "This") -> None:
    """Every month touched by the range must be open."""
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        ensure_open(date(year, month, 1), what)
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
