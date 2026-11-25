from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.audit.service import record
from core.company.models import Company

from . import payslip_pdf, reports, service
from .models import PayrollLine, PayrollPeriod, PayrollRun


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


# --- Reports and payslips --------------------------------------------------------------


def _company_info() -> payslip_pdf.CompanyInfo:
    company = Company.objects.filter(pk=1).first()
    if company is None:
        return payslip_pdf.CompanyInfo(name="")
    address = ", ".join(x for x in (company.address, company.city) if x)
    return payslip_pdf.CompanyInfo(
        name=company.trade_name or company.legal_name,
        tin=company.tin,
        address=address,
        currency=company.currency_code,
    )


def _pdf_response(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


def _run_for(year, month) -> PayrollRun:
    return get_object_or_404(PayrollRun.objects.select_related("period"), period__year=year, period__month=month)


@login_required
@permission_required("payroll.view_payrollline", raise_exception=True)
@require_GET
def report_csv(request, year, month, key):
    run = _run_for(year, month)
    build = reports.REPORTS.get(key)
    if build is None:
        raise Http404("No such report.")
    # Never hand out a list of payments from figures that have not been approved.
    if key == "bank-transfer" and not run.is_locked:
        messages.error(request, "The bank transfer list is only available once the payroll is locked.")
        return redirect("payroll:run", year=year, month=month)
    report = build(run.lines.all())
    record("payroll.report_exported", obj=run, changes={"report": key, "rows": len(report.rows)})
    suffix = "" if run.is_locked else "-DRAFT"
    response = HttpResponse(reports.to_csv(report), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{key}-{year}-{month:02d}{suffix}.csv"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@permission_required("payroll.view_payrollline", raise_exception=True)
@require_GET
def payslips_pdf(request, year, month):
    run = _run_for(year, month)
    lines = list(run.lines.all())
    if not lines:
        messages.error(request, "There are no payslips to print.")
        return redirect("payroll:run", year=year, month=month)
    content = payslip_pdf.bulk_payslips_pdf(
        lines, run.period.label, _company_info(), draft=not run.is_locked, font_path=settings.EMS_PDF_FONT_PATH
    )
    record("payroll.payslips_exported", obj=run, changes={"payslips": len(lines)})
    return _pdf_response(content, f"payslips-{year}-{month:02d}{'' if run.is_locked else '-DRAFT'}.pdf")


@login_required
@permission_required("payroll.view_payrollline", raise_exception=True)
@require_GET
def payslip(request, pk):
    line = get_object_or_404(PayrollLine.objects.select_related("run__period"), pk=pk)
    return _one_payslip(line, draft=not line.run.is_locked)


def _one_payslip(line: PayrollLine, *, draft: bool) -> HttpResponse:
    period = line.run.period
    content = payslip_pdf.payslip_pdf(
        line, period.label, _company_info(), draft=draft, font_path=settings.EMS_PDF_FONT_PATH
    )
    record(
        "payroll.payslip_viewed",
        obj=line.run,
        changes={"employee_number": line.employee_number},
    )
    return _pdf_response(content, f"payslip-{line.employee_number}-{period.year}-{period.month:02d}.pdf")


def _own_employee(user):
    """The employee record linked to this sign-in, or None."""
    return getattr(user, "employee", None)


@login_required
@require_GET
def my_payslips(request):
    employee = _own_employee(request.user)
    lines = []
    if employee is not None:
        lines = list(
            PayrollLine.objects.filter(employee=employee, run__status=PayrollRun.Status.LOCKED)
            .select_related("run__period")
            .order_by("-run__period__year", "-run__period__month")
        )
    return render(request, "payroll/my_payslips.html", {"employee": employee, "lines": lines})


@login_required
@require_GET
def my_payslip(request, pk):
    employee = _own_employee(request.user)
    # Someone else's payslip, or one not yet approved, looks exactly like one that does not exist.
    if employee is None:
        raise Http404("No such payslip.")
    line = get_object_or_404(
        PayrollLine.objects.select_related("run__period"),
        pk=pk,
        employee=employee,
        run__status=PayrollRun.Status.LOCKED,
    )
    return _one_payslip(line, draft=False)
