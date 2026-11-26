"""Leave workflow: request, approve or reject, cancel. Every step is audited."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import ExtractYear
from django.utils import timezone

from core import workcalendar
from core.audit.service import record
from modules.hr.models import Employee
from modules.hr.rules import LEFT_STATUSES

from . import logic
from .models import LeaveAdjustment, LeaveRequest, LeaveType

APPROVE = "leave.approve_leaverequest"
ADD = "leave.add_leaverequest"


class LeaveRefused(Exception):
    """The request cannot be accepted. The message is safe to show the user."""


def count_days(start: date, end: date, half_day: bool = False) -> Decimal:
    try:
        return logic.count_leave_days(
            start, end, rest_day=workcalendar.rest_day(end), holidays=workcalendar.public_holidays(start, end), half_day=half_day
        )
    except logic.LeaveError as exc:
        raise LeaveRefused(str(exc)) from exc


def balance(employee: Employee, leave_type: LeaveType, year: int) -> logic.Balance:
    used = defaultdict(Decimal)
    rows = (
        LeaveRequest.objects.filter(employee=employee, leave_type=leave_type, status=LeaveRequest.Status.APPROVED)
        .annotate(y=ExtractYear("start_date"))
        .values("y")
        .annotate(total=Sum("days"))
    )
    for row in rows:
        used[row["y"]] = row["total"]
    adjustments = defaultdict(Decimal)
    for row in (
        LeaveAdjustment.objects.filter(employee=employee, leave_type=leave_type).values("year").annotate(t=Sum("days"))
    ):
        adjustments[row["year"]] = row["t"]
    return logic.balance_for(
        year,
        base_days=leave_type.annual_days,
        extra_day_every_years=leave_type.extra_day_every_years,
        hire_date=employee.employment_date,
        used_by_year=used,
        adjustments_by_year=adjustments,
        carry_over_max=leave_type.carry_over_max,
        prorate_first_year=leave_type.prorate_first_year,
    )


def _pending_days(employee, leave_type, year, exclude_pk=None) -> Decimal:
    qs = LeaveRequest.objects.filter(
        employee=employee, leave_type=leave_type, status=LeaveRequest.Status.PENDING, start_date__year=year
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.aggregate(t=Sum("days"))["t"] or Decimal("0")


def _check_overlap(employee, start, end, exclude_pk=None):
    clash = LeaveRequest.objects.filter(
        employee=employee,
        status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
        start_date__lte=end,
        end_date__gte=start,
    )
    if exclude_pk:
        clash = clash.exclude(pk=exclude_pk)
    other = clash.first()
    if other:
        raise LeaveRefused(
            f"This overlaps another {other.get_status_display().lower()} request "
            f"({other.start_date} to {other.end_date})."
        )


def _check_balance(employee, leave_type, year, days, exclude_pk=None):
    if not leave_type.uses_balance:
        return
    bal = balance(employee, leave_type, year)
    available = bal.remaining - _pending_days(employee, leave_type, year, exclude_pk)
    if days > available:
        raise LeaveRefused(
            f"Not enough {leave_type.name.lower()} for {year}: {available} day(s) available, {days} requested."
        )


def _is_own(employee: Employee, user) -> bool:
    return user is not None and employee.user_id is not None and employee.user_id == user.pk


@transaction.atomic
def request_leave(employee: Employee, leave_type: LeaveType, start: date, end: date, user, *,
                  half_day: bool = False, reason: str = "") -> LeaveRequest:
    """An employee asks for their own leave, or HR asks on their behalf."""
    if user is None or not (_is_own(employee, user) or user.has_perm(ADD)):
        raise PermissionDenied("You can only request leave for yourself.")
    if not leave_type.is_active:
        raise LeaveRefused(f"{leave_type.name} is not available.")
    if employee.status in LEFT_STATUSES:
        raise LeaveRefused("This employee has left.")
    if start < employee.employment_date:
        raise LeaveRefused("This is before the employee's start date.")
    days = count_days(start, end, half_day)
    # Lock the employee's row so two requests at once cannot both spend the last days.
    Employee.objects.select_for_update().get(pk=employee.pk)
    _check_overlap(employee, start, end)
    _check_balance(employee, leave_type, start.year, days)
    request = LeaveRequest.objects.create(
        employee=employee, leave_type=leave_type, start_date=start, end_date=end, half_day=half_day,
        days=days, reason=reason, requested_by=user,
    )
    record("leave.requested", obj=request, actor=user, changes={"days": str(days), "type": leave_type.name})
    return request


def _locked(request: LeaveRequest) -> LeaveRequest:
    return LeaveRequest.objects.select_for_update(of=("self",)).select_related("employee", "leave_type").get(pk=request.pk)


@transaction.atomic
def decide(request: LeaveRequest, user, *, approve: bool, note: str = "") -> LeaveRequest:
    """Approve or reject a pending request. Not your own: someone else must decide."""
    if user is None or not user.has_perm(APPROVE):
        raise PermissionDenied(f"You do not have permission: {APPROVE}")
    fresh = _locked(request)
    if _is_own(fresh.employee, user):
        raise LeaveRefused("You cannot decide your own leave request. Ask someone else to.")
    if fresh.status != LeaveRequest.Status.PENDING:
        raise LeaveRefused(f"This request is already {fresh.get_status_display().lower()}.")
    if approve:
        _check_overlap(fresh.employee, fresh.start_date, fresh.end_date, exclude_pk=fresh.pk)
        _check_balance(fresh.employee, fresh.leave_type, fresh.start_date.year, fresh.days, exclude_pk=fresh.pk)
    fresh.status = LeaveRequest.Status.APPROVED if approve else LeaveRequest.Status.REJECTED
    fresh.decided_by, fresh.decided_at, fresh.decision_note = user, timezone.now(), note
    fresh.save()
    record("leave.approved" if approve else "leave.rejected", obj=fresh, actor=user, changes={"note": note})
    return fresh


@transaction.atomic
def cancel(request: LeaveRequest, user) -> LeaveRequest:
    """The person who asked can withdraw a pending request. Only an approver can cancel
    leave that was already approved."""
    fresh = _locked(request)
    if user is None:
        raise PermissionDenied("Sign in to cancel a request.")
    allowed_pending = _is_own(fresh.employee, user) or fresh.requested_by_id == user.pk or user.has_perm(APPROVE)
    if fresh.status == LeaveRequest.Status.PENDING:
        if not allowed_pending:
            raise PermissionDenied("You cannot cancel this request.")
    elif fresh.status == LeaveRequest.Status.APPROVED:
        if not user.has_perm(APPROVE):
            raise PermissionDenied("Only an approver can cancel approved leave.")
    else:
        raise LeaveRefused(f"This request is already {fresh.get_status_display().lower()}.")
    old = fresh.status
    fresh.status = LeaveRequest.Status.CANCELLED
    fresh.save()
    record("leave.cancelled", obj=fresh, actor=user, changes={"was": old})
    return fresh
