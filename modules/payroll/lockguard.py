"""Tells core.period_lock which dates belong to a locked payroll month."""
from __future__ import annotations

from datetime import date

from .models import PayrollRun


def is_locked(day: date) -> bool:
    return PayrollRun.objects.filter(
        status=PayrollRun.Status.LOCKED, period__year=day.year, period__month=day.month
    ).exists()
