from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from modules.hr.models import Employee

from . import service
from .models import OvertimeCategory, OvertimeEntry


def _own_employee(user):
    return getattr(user, "employee", None)


def _parse_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _target_employee(request):
    number = (request.POST.get("employee_number") or "").strip()
    if number and request.user.has_perm(service.ADD):
        employee = Employee.objects.filter(employee_number=number).first()
        if employee is None:
            raise service.OvertimeRefused(f"No employee has the number {number!r}.")
        return employee
    employee = _own_employee(request.user)
    if employee is None:
        raise service.OvertimeRefused("Your sign-in is not linked to an employee record. Ask HR to link it.")
    return employee


@login_required
@require_GET
def my_overtime(request):
    employee = _own_employee(request.user)
    entries = list(employee.overtime_entries.select_related("category")[:50]) if employee else []
    return render(
        request,
        "overtime/my_overtime.html",
        {
            "employee": employee,
            "entries": entries,
            "categories": OvertimeCategory.objects.filter(is_active=True),
            "can_record_for_others": request.user.has_perm(service.ADD),
        },
    )


@login_required
@require_POST
def record(request):
    try:
        employee = _target_employee(request)
        day = _parse_date(request.POST.get("work_date"))
        if day is None:
            raise service.OvertimeRefused("Enter the date the overtime was worked.")
        service.record_overtime(
            employee, day, request.POST.get("hours", ""), request.POST.get("kind", ""), request.user,
            reason=(request.POST.get("reason") or "").strip()[:255],
        )
        messages.success(request, "Overtime recorded. It is paid once it has been approved.")
    except service.OvertimeRefused as exc:
        messages.error(request, str(exc))
    return redirect("overtime:mine")


@login_required
@require_POST
def cancel(request, pk):
    entry = get_object_or_404(OvertimeEntry.objects.select_related("employee"), pk=pk)
    mine = _own_employee(request.user)
    if not ((mine and entry.employee_id == mine.pk) or request.user.has_perm(service.APPROVE)):
        raise Http404("No such entry.")
    try:
        service.cancel(entry, request.user)
        messages.success(request, "Overtime cancelled.")
    except service.OvertimeRefused as exc:
        messages.error(request, str(exc))
    return redirect("overtime:approvals" if request.POST.get("next") == "approvals" else "overtime:mine")


@login_required
@permission_required(service.APPROVE, raise_exception=True)
@require_GET
def approvals(request):
    pending = list(
        OvertimeEntry.objects.filter(status=OvertimeEntry.Status.PENDING)
        .select_related("employee", "category")
        .order_by("work_date")
    )
    for item in pending:
        item.is_mine = bool(item.employee.user_id and item.employee.user_id == request.user.pk)
    recent = OvertimeEntry.objects.exclude(status=OvertimeEntry.Status.PENDING).select_related(
        "employee", "category", "decided_by"
    )[:25]
    return render(request, "overtime/approvals.html", {"pending": pending, "recent": recent})


@login_required
@require_POST
def decide(request, pk):
    entry = get_object_or_404(OvertimeEntry, pk=pk)
    action = request.POST.get("action")
    if action not in ("approve", "reject"):
        messages.error(request, "Unknown action.")
        return redirect("overtime:approvals")
    try:
        service.decide(entry, request.user, approve=action == "approve", note=(request.POST.get("note") or "").strip()[:255])
        messages.success(request, "Approved." if action == "approve" else "Rejected.")
    except service.OvertimeRefused as exc:
        messages.error(request, str(exc))
    return redirect("overtime:approvals")
