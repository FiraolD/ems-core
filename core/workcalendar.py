"""The working calendar: the weekly rest day and public holidays, shared by leave and overtime.

Public holidays come from the attendance module when it is enabled; without it there are none.
"""
from __future__ import annotations

from datetime import date

from django.apps import apps

from core.rules.service import rules_for


def rest_day(on: date) -> int:
    """Python weekday number (Monday 0 ... Sunday 6) of the weekly rest day in force on a date."""
    return getattr(rules_for(on).rules, "weekly_rest_day", 6)


def public_holidays(start: date, end: date) -> set[date]:
    if not apps.is_installed("modules.attendance"):
        return set()
    from modules.attendance.models import PublicHoliday

    return set(PublicHoliday.objects.filter(date__range=(start, end)).values_list("date", flat=True))
