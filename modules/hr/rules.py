"""HR rules that need no database: who is on payroll in a period, and which salary applies.

No Django imports, so these are unit-tested without a database.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Protocol

ACTIVE = "active"
ON_LEAVE = "on_leave"
SUSPENDED = "suspended"
RESIGNED = "resigned"
TERMINATED = "terminated"
RETIRED = "retired"

STATUSES = (ACTIVE, ON_LEAVE, SUSPENDED, RESIGNED, TERMINATED, RETIRED)
WORKING_STATUSES = (ACTIVE, ON_LEAVE)
LEFT_STATUSES = (RESIGNED, TERMINATED, RETIRED)


def eligible_for_period(
    employment_date: date | None,
    status: str,
    termination_date: date | None,
    period_start: date,
    period_end: date,
) -> bool:
    """Whether an employee belongs in a pay period running period_start..period_end.

    - Not yet hired by the end of the period: no.
    - Suspended: no.
    - Left (resigned, terminated, retired) before the period began: no. A leaver with no
      termination date is still included, so that a missing date is noticed on the payroll
      rather than silently dropping someone from pay.
    """
    if period_end < period_start:
        raise ValueError("period_end is before period_start")
    if employment_date and employment_date > period_end:
        return False
    if status == SUSPENDED:
        return False
    return not (status in LEFT_STATUSES and termination_date and termination_date < period_start)


class HasEffectiveDate(Protocol):
    effective_date: date


def record_on(records: Iterable[HasEffectiveDate], as_of: date):
    """The record in force on ``as_of``: the latest one effective on or before that date.

    Returns None when nothing is effective yet. Records on the same date should not exist
    (the database forbids it); if they do, the last one given wins.
    """
    chosen = None
    for record in records:
        if record.effective_date <= as_of and (
            chosen is None or record.effective_date >= chosen.effective_date
        ):
            chosen = record
    return chosen


def salary_for_period(records: Iterable[HasEffectiveDate], period_start: date, period_end: date):
    """The salary record that pays for the month period_start..period_end, or None.

    - The first record an employee ever had (their starting salary) applies from its date, so
      someone hired mid-month is paid for that month.
    - Any later record (a raise or other change) applies from the next month, unless it is
      dated the 1st of a month, when it applies to that month. A raise decided on 15 September
      therefore first pays in October.

    Of the records that apply, the latest wins.
    """
    ordered = sorted(records, key=lambda record: record.effective_date)
    if not ordered:
        return None
    first = ordered[0]
    chosen = None
    for record in ordered:
        limit = period_end if record is first else period_start
        if record.effective_date <= limit:
            chosen = record
    return chosen
