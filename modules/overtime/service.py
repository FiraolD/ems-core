"""Overtime workflow: record, approve or reject, cancel. Every step is audited."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from core import workcalendar
from core.audit.service import record
from modules.hr.models import Employee
from modules.hr.rules import LEFT_STATUSES

from . import logic
from .models import OvertimeCategory, OvertimeEntry

APPROVE = "overtime.approve_overtimeentry"
ADD = "overtime.add_overtimeentry"


class OvertimeRefused(Exception):
    """The overtime cannot be accepted. The message is safe to show the user."""


def _is_own(employee: Employee, user) -> bool:
    return user is not None and employee.user_id is not None and employee.user_id == user.pk


@transaction.atomic
def record_overtime(employee: Employee, work_date: date, hours, kind: str, user, *, reason: str = "") -> OvertimeEntry:
    """An employee reports their own overtime, or HR records it for them."""
    if user is None or not (_is_own(employee, user) or user.has_perm(ADD)):
        raise PermissionDenied("You can only record overtime for yourself.")
    if employee.status in LEFT_STATUSES:
        raise OvertimeRefused("This employee has left.")
    if work_date < employee.employment_date:
        raise OvertimeRefused("This is before the employee's start date.")
    if work_date > timezone.localdate():
        raise OvertimeRefused("Overtime cannot be recorded for a future date.")
    category = OvertimeCategory.objects.filter(kind=kind, is_active=True).first()
    if category is None:
        raise OvertimeRefused("There is no active rate for that kind of overtime. Ask HR to set it up.")
    try:
        hours = logic.validate_entry(
            kind, work_date, hours,
            rest_day=workcalendar.rest_day(work_date),
            holidays=workcalendar.public_holidays(work_date, work_date),
        )
    except logic.OvertimeError as exc:
        raise OvertimeRefused(str(exc)) from exc
    entry = OvertimeEntry.objects.create(
        employee=employee, work_date=work_date, hours=hours, category=category,
        multiplier=category.multiplier, reason=reason, requested_by=user,
    )
    record("overtime.requested", obj=entry, actor=user, changes={"hours": str(hours), "kind": kind})
    return entry


def _locked(entry: OvertimeEntry) -> OvertimeEntry:
    return OvertimeEntry.objects.select_for_update(of=("self",)).select_related("employee").get(pk=entry.pk)


@transaction.atomic
def decide(entry: OvertimeEntry, user, *, approve: bool, note: str = "") -> OvertimeEntry:
    if user is None or not user.has_perm(APPROVE):
        raise PermissionDenied(f"You do not have permission: {APPROVE}")
    fresh = _locked(entry)
    if _is_own(fresh.employee, user):
        raise OvertimeRefused("You cannot decide your own overtime. Ask someone else to.")
    if fresh.status != OvertimeEntry.Status.PENDING:
        raise OvertimeRefused(f"This entry is already {fresh.get_status_display().lower()}.")
    fresh.status = OvertimeEntry.Status.APPROVED if approve else OvertimeEntry.Status.REJECTED
    fresh.decided_by, fresh.decided_at, fresh.decision_note = user, timezone.now(), note
    fresh.save()
    record("overtime.approved" if approve else "overtime.rejected", obj=fresh, actor=user, changes={"note": note})
    return fresh


@transaction.atomic
def cancel(entry: OvertimeEntry, user) -> OvertimeEntry:
    """The person who recorded it can withdraw a pending entry; only an approver can cancel
    approved overtime."""
    fresh = _locked(entry)
    if user is None:
        raise PermissionDenied("Sign in to cancel overtime.")
    if fresh.status == OvertimeEntry.Status.PENDING:
        if not (_is_own(fresh.employee, user) or fresh.requested_by_id == user.pk or user.has_perm(APPROVE)):
            raise PermissionDenied("You cannot cancel this entry.")
    elif fresh.status == OvertimeEntry.Status.APPROVED:
        if not user.has_perm(APPROVE):
            raise PermissionDenied("Only an approver can cancel approved overtime.")
    else:
        raise OvertimeRefused(f"This entry is already {fresh.get_status_display().lower()}.")
    old = fresh.status
    fresh.status = OvertimeEntry.Status.CANCELLED
    fresh.save()
    record("overtime.cancelled", obj=fresh, actor=user, changes={"was": old})
    return fresh


def approved_entries(employee: Employee, start: date, end: date) -> list[tuple[Decimal, Decimal]]:
    """(hours, multiplier) of approved overtime worked in a date range, for payroll."""
    return list(
        OvertimeEntry.objects.filter(
            employee=employee, status=OvertimeEntry.Status.APPROVED, work_date__range=(start, end)
        ).values_list("hours", "multiplier")
    )
