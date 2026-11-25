from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import service
from .models import PayrollPeriod, PayrollRun


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@login_required
@permission_required("payroll.view_payrollrun", raise_exception=True)
def index(request):
    runs = PayrollRun.objects.select_related("period").all()
    rows = [(run, service.run_totals(run)) for run in runs]
    return render(request, "payroll/index.html", {"rows": rows})


@login_required
@permission_required("payroll.view_payrollrun", raise_exception=True)
def run_detail(request, year, month):
    period = get_object_or_404(PayrollPeriod, year=year, month=month)
    run = get_object_or_404(PayrollRun.objects.select_related("calculated_by", "locked_by"), period=period)
    can_calculate = request.user.has_perm(service.CALCULATE)
    can_lock = request.user.has_perm(service.LOCK)
    status = run.status
    context = {
        "run": run,
        "period": period,
        "lines": run.lines.all(),
        "totals": service.run_totals(run),
        "can_calculate": can_calculate,
        "can_lock": can_lock,
        "can_recalculate": can_calculate and status == PayrollRun.Status.DRAFT,
        "can_submit": can_calculate and status == PayrollRun.Status.DRAFT,
        "can_return": can_calculate and status == PayrollRun.Status.REVIEW,
        "can_lock_now": can_lock and status == PayrollRun.Status.REVIEW,
        "intact": service.verify_run(run) if run.is_locked else None,
    }
    return render(request, "payroll/run.html", context)


@login_required
@require_POST
def calculate(request):
    year, month = _int(request.POST.get("year")), _int(request.POST.get("month"))
    if year is None or month is None:
        messages.error(request, "Choose a year and a month.")
        return redirect("payroll:index")
    try:
        run = service.calculate_run(year, month, request.user)
    except PermissionDenied:
        raise
    except service.PayrollError as exc:
        messages.error(request, str(exc))
        return redirect("payroll:index")
    skipped = len(run.skipped)
    messages.success(
        request,
        f"Calculated {run.period.label}: {run.lines.count()} employees"
        + (f", {skipped} could not be calculated (see below)." if skipped else "."),
    )
    return redirect("payroll:run", year=year, month=month)


@login_required
@require_POST
def act(request, year, month, action):
    run = get_object_or_404(PayrollRun, period__year=year, period__month=month)
    try:
        if action == "recalculate":
            service.calculate_run(year, month, request.user)
            messages.success(request, "Recalculated.")
        elif action == "submit":
            service.submit_for_review(run, request.user)
            messages.success(request, "Submitted for review.")
        elif action == "return":
            service.return_to_draft(run, request.user)
            messages.success(request, "Returned to draft.")
        elif action == "lock":
            service.lock_run(run, request.user, request.POST.get("password", ""))
            messages.success(request, f"{run.period.label} is locked. It can no longer be changed.")
        else:
            messages.error(request, "Unknown action.")
    except PermissionDenied:
        raise
    except service.PayrollError as exc:
        messages.error(request, str(exc))
    return redirect("payroll:run", year=year, month=month)
