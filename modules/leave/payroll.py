"""Feeds approved leave into payroll, and lets it excuse recorded absences."""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings

from core import workcalendar
from countries import get_pack

from .models import LeaveRequest, LeaveType

ORDER = 200  # after attendance (100): approved leave overrides an absence on the same day
EXCUSED = ("absent", "half_day")


def leave_days(employee, period_start, period_end):
    """(day, leave type, half_day) for each working day of approved leave inside the period."""
    requests = LeaveRequest.objects.filter(
        employee=employee,
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=period_end,
        end_date__gte=period_start,
    ).select_related("leave_type")
    rest = workcalendar.rest_day(period_end)
    holidays = workcalendar.public_holidays(period_start, period_end)
    out = []
    for req in requests:
        day, last = max(req.start_date, period_start), min(req.end_date, period_end)
        while day <= last:
            if day.weekday() != rest and day not in holidays:
                out.append((day, req.leave_type, req.half_day))
            day += timedelta(days=1)
    return out


def add_leave(inputs, *, employee, period_start, period_end):
    day_record = get_pack(settings.EMS_CLIENT.country_pack).DayRecord
    full_days = set()
    for day, leave_type, half_day in leave_days(employee, period_start, period_end):
        unpaid = leave_type.pay_code == LeaveType.PayCode.UNPAID
        if half_day:
            # A paid half day changes nothing the pay rules count; an unpaid one is half a day off.
            if unpaid:
                inputs.attendance.append(day_record(day, "half_day"))
            continue
        full_days.add(day)
        inputs.attendance.append(day_record(day, leave_type.pay_code))
    # Approved full-day leave excuses an absence recorded for the same day.
    inputs.attendance[:] = [
        r for r in inputs.attendance if not (r.day in full_days and r.status in EXCUSED)
    ]
    return inputs


def register() -> None:
    from core.extensions.registry import registry
    from modules.payroll import inputs

    registry.register_once(inputs.HOOK, add_leave, order=ORDER)
