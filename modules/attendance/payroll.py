"""Feeds recorded absences and half days into payroll."""
from __future__ import annotations

from django.conf import settings

from countries import get_pack

from . import logic
from .models import AttendanceRecord

ORDER = 100  # before leave (200), which excuses absences on approved leave days


def add_attendance(inputs, *, employee, period_start, period_end):
    day_record = get_pack(settings.EMS_CLIENT.country_pack).DayRecord
    rows = AttendanceRecord.objects.filter(
        employee=employee, date__range=(period_start, period_end), status__in=list(logic.PAY_AFFECTING)
    ).values_list("date", "status")
    inputs.attendance.extend(day_record(day, status) for day, status in logic.pay_statuses(rows))
    return inputs


def register() -> None:
    from core.extensions.registry import registry
    from modules.payroll import inputs

    registry.register_once(inputs.HOOK, add_attendance, order=ORDER)
