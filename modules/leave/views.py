from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from modules.hr.models import Employee

from . import service
from .models import LeaveRequest, LeaveType


def _own_employee(user):
    return getattr(user, "employee", None)


def _parse_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _target_employee(request):
    """Whose leave this is: the signed-in person's, or (for HR) the employee number typed in."""
    number = (request.POST.get("employee_number") or "").strip()
    if number and request.user.has_perm(service.ADD):
        employee = Employee.objects.filter(employee_number=number).first()
        if employee is None:
            raise service.LeaveRefused(f"No employee has the number {number!r}.")
        return employee
    employee = _own_employee(request.user)
    if employee is None:
        raise service.LeaveRefused("Your sign-in is not linked to an employee record. Ask HR to link it.")
    return employee


@login_required
@require_GET
def my_leave(request):
    employee = _own_employee(request.user)
    year = timezone.localdate().year
    balances, requests = [], []
    if employee is not None:
        for leave_type in LeaveType.objects.filter(is_active=True, uses_balance=True):
            balances.append((leave_type, service.balance(employee, leave_type, year)))
        requests = list(employee.leave_requests.select_related("leave_type")[:50])
    return render(
        request,
        "leave/my_leave.html",
        {
            "employee": employee,
            "year": year,
            "balances": balances,
            "requests": requests,
            "types": LeaveType.objects.filter(is_active=True),
            "can_request_for_others": request.user.has_perm(service.ADD),
        },
    )


@login_required
@require_POST
def request_leave(request):
    try:
        employee = _target_employee(request)
        leave_type = get_object_or_404(LeaveType, pk=request.POST.get("leave_type") or 0)
        start, end = _parse_date(request.POST.get("start_date")), _parse_date(request.POST.get("end_date"))
        if start is None or end is None:
            raise service.LeaveRefused("Enter the first and last day of leave.")
        if request.POST.get("half_day") and not request.POST.get("end_date"):
            end = start
        service.request_leave(
            employee, leave_type, start, end, request.user,
            half_day=bool(request.POST.get("half_day")), reason=(request.POST.get("reason") or "").strip()[:255],
        )
        messages.success(request, "Leave requested. You will see it here once it has been decided.")
    except service.LeaveRefused as exc:
        messages.error(request, str(exc))
    return redirect("leave:mine")


@login_required
@require_POST
def cancel(request, pk):
    leave = get_object_or_404(LeaveRequest.objects.select_related("employee"), pk=pk)
    mine = _own_employee(request.user)
    # Someone else's request looks like one that does not exist, unless you approve leave.
    if not ((mine and leave.employee_id == mine.pk) or request.user.has_perm(service.APPROVE)):
        raise Http404("No such request.")
    try:
        service.cancel(leave, request.user)
        messages.success(request, "Leave request cancelled.")
    except service.LeaveRefused as exc:
        messages.error(request, str(exc))
    return redirect("leave:approvals" if request.POST.get("next") == "approvals" else "leave:mine")


@login_required
@permission_required(service.APPROVE, raise_exception=True)
@require_GET
def approvals(request):
    pending = list(
        LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING)
        .select_related("employee", "leave_type")
        .order_by("start_date")
    )
    for item in pending:
        item.available = (
            service.balance(item.employee, item.leave_type, item.start_date.year).remaining
            if item.leave_type.uses_balance
            else None
        )
        item.is_mine = bool(item.employee.user_id and item.employee.user_id == request.user.pk)
    recent = LeaveRequest.objects.exclude(status=LeaveRequest.Status.PENDING).select_related(
        "employee", "leave_type", "decided_by"
    )[:25]
    return render(request, "leave/approvals.html", {"pending": pending, "recent": recent})


@login_required
@require_POST
def decide(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    action = request.POST.get("action")
    if action not in ("approve", "reject"):
        messages.error(request, "Unknown action.")
        return redirect("leave:approvals")
    try:
        service.decide(leave, request.user, approve=action == "approve", note=(request.POST.get("note") or "").strip()[:255])
        messages.success(request, "Approved." if action == "approve" else "Rejected.")
    except service.LeaveRefused as exc:
        messages.error(request, str(exc))
    return redirect("leave:approvals")
