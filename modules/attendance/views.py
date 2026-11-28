import calendar
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from core.audit.service import record
from core.csvsafe import write_csv
from modules.hr.models import Employee

from . import logic, service
from .models import AttendanceRecord

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
SHOWN_ERRORS = 30


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _month(request):
    today = timezone.localdate()
    year, month = _int(request.GET.get("year"), today.year), _int(request.GET.get("month"), today.month)
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        year, month = today.year, today.month
    return year, month


def _summary(year, month):
    start, end = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    people = [
        (e.employee_number, e.full_name)
        for e in Employee.objects.all()
        if e.eligible_for_period(start, end)
    ]
    records = AttendanceRecord.objects.filter(date__range=(start, end)).values_list("employee__employee_number", "status")
    return logic.monthly_summary(people, records)


@login_required
@permission_required(service.IMPORT, raise_exception=True)
@require_http_methods(["GET", "POST"])
def import_view(request):
    context = {"errors": [], "more_errors": 0}
    if request.method == "POST":
        upload = request.FILES.get("file")
        if upload is None:
            messages.error(request, "Choose a CSV file to import.")
        elif upload.size > MAX_UPLOAD_BYTES:
            messages.error(request, "That file is too large. Split it by month and try again.")
        else:
            try:
                text = upload.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                messages.error(request, "The file is not UTF-8 text. In Excel, save it as 'CSV UTF-8'.")
            else:
                try:
                    summary = service.import_csv(text, request.user, today=timezone.localdate())
                except service.ImportRejected as exc:
                    context["errors"] = exc.errors[:SHOWN_ERRORS]
                    context["more_errors"] = max(len(exc.errors) - SHOWN_ERRORS, 0)
                else:
                    messages.success(
                        request,
                        f"Imported: {summary.created} added, {summary.updated} changed, {summary.unchanged} unchanged.",
                    )
                    return redirect("attendance:import")
    return render(request, "attendance/import.html", context)


@login_required
@permission_required("attendance.view_attendancerecord", raise_exception=True)
@require_GET
def report(request):
    year, month = _month(request)
    rows, totals = _summary(year, month)
    return render(
        request,
        "attendance/report.html",
        {"year": year, "month": month, "label": date(year, month, 1).strftime("%B %Y"),
         "headers": logic.SUMMARY_HEADERS, "rows": rows, "totals": totals},
    )


@login_required
@permission_required("attendance.view_attendancerecord", raise_exception=True)
@require_GET
def report_csv(request, year, month):
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return redirect("attendance:report")
    rows, totals = _summary(year, month)
    record(
        "attendance.report_exported",
        object_type="attendance.attendancerecord",
        object_repr=f"{year}-{month:02d}",
        changes={"rows": len(rows)},
    )
    response = HttpResponse(write_csv(logic.SUMMARY_HEADERS, rows, totals), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="attendance-{year}-{month:02d}.csv"'
    response["Cache-Control"] = "private, no-store"
    return response
