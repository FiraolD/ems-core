"""Payroll workflow: calculate, submit for review, return to draft, lock.

Every state change is audited. Locking asks for the user's password again.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone

from core.audit.service import record
from core.money import money
from core.rules.service import rules_for
from countries import get_pack
from modules.hr.models import Employee
from modules.hr.rules import LEFT_STATUSES

from . import inputs as pay_inputs
from .integrity import lines_digest
from .models import Bonus, PayrollLine, PayrollPeriod, PayrollRun, SalaryAdvance

CALCULATE = "payroll.calculate_payrollrun"
LOCK = "payroll.lock_payrollrun"


class PayrollError(Exception):
    """The payroll cannot do what was asked. The message is safe to show the user."""


class PayrollStateError(PayrollError):
    """The run is not in a state where this is allowed."""


class PasswordConfirmationError(PayrollError):
    """The password given to confirm locking was wrong."""


def _require(user, permission: str):
    if user is None or not user.has_perm(permission):
        raise PermissionDenied(f"You do not have permission: {permission}")


def get_period(year: int, month: int) -> PayrollPeriod:
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        raise PayrollError("Choose a valid year and month.")
    period, _ = PayrollPeriod.objects.get_or_create(year=year, month=month)
    return period


def _month_amounts(model, field_filter: dict) -> dict[int, Decimal]:
    rows = model.objects.filter(**field_filter).values("employee_id").annotate(total=Sum("amount"))
    return {row["employee_id"]: row["total"] for row in rows}


def _skipped(employee: Employee, reason: str) -> dict:
    return {"employee_number": employee.employee_number, "name": employee.full_name, "reason": reason}


@transaction.atomic
def calculate_run(year: int, month: int, user=None) -> PayrollRun:
    """(Re)calculate a month's payroll. Only a draft can be calculated.

    ``user`` is None when run by the system (for example from the command line). Employees
    who are due pay but cannot be calculated are listed on the run, never dropped silently.
    """
    if user is not None:
        _require(user, CALCULATE)
    period = get_period(year, month)
    run, _ = PayrollRun.objects.select_for_update().get_or_create(period=period)
    if run.status != PayrollRun.Status.DRAFT:
        raise PayrollStateError(
            f"{period.label} is {run.get_status_display().lower()}. "
            "Return it to draft before recalculating."
        )

    start, end = period.start_date, period.end_date
    found = rules_for(end)
    pack = get_pack(settings.EMS_CLIENT.country_pack)

    bonuses = _month_amounts(Bonus, {"year": year, "month": month, "approved": True})
    advances = _month_amounts(SalaryAdvance, {"year": year, "month": month})

    lines, skipped = [], []
    employees = (
        Employee.objects.select_related("department", "position")
        .prefetch_related("salary_records")
        .order_by("employee_number")
    )
    for employee in employees:
        if not employee.eligible_for_period(start, end):
            continue
        salary = employee.salary_for_period(start, end)
        if salary is None:
            skipped.append(_skipped(employee, f"No salary record applies to {period.label}."))
            continue

        gathered = pay_inputs.gather(
            pay_inputs.EmployeeInputs(
                bonus=bonuses.get(employee.pk, Decimal("0")),
                salary_advance=advances.get(employee.pk, Decimal("0")),
            ),
            employee=employee,
            period_start=start,
            period_end=end,
        )
        slip = pack.compute_payslip(
            pack.PayslipInput(
                period_start=start,
                period_end=end,
                basic_salary=salary.basic_salary,
                transport_allowance=salary.transport_allowance,
                other_allowances=salary.other_allowances,
                other_allowances_taxable=salary.other_allowances_taxable,
                overtime_pay=gathered.overtime_pay,
                bonus=gathered.bonus,
                salary_advance=gathered.salary_advance,
                hire_date=employee.employment_date,
                termination_date=employee.termination_date if employee.status in LEFT_STATUSES else None,
                attendance=gathered.attendance,
            ),
            found.rules,
            found.brackets,
        )
        lines.append(
            PayrollLine(
                run=run,
                employee=employee,
                employee_number=employee.employee_number,
                employee_name=employee.full_name,
                tin=employee.tin,
                department=employee.department.name if employee.department else "",
                position=employee.position.title if employee.position else "",
                bank_name=employee.bank_name,
                bank_account_number=employee.bank_account_number,
                basic_salary=slip.basic_salary,
                basic_earned=slip.basic_earned,
                days_worked=slip.days_worked,
                transport_payable=slip.transport_payable,
                other_allowances=slip.other_allowances,
                overtime_pay=slip.overtime_pay,
                bonus=slip.bonus,
                gross_earnings=slip.gross_earnings,
                unpaid_days=slip.absence.unpaid_days,
                paid_leave_days=slip.absence.leave_transport_days,
                absence_deduction=slip.absence.basic_deduction,
                taxable_income=slip.taxable_income,
                tax_rate=slip.tax.rate,
                paye=slip.tax.paye,
                bonus_tax=slip.bonus_tax,
                pensionable_salary=slip.pensionable_salary,
                pension_prorated=slip.pension_prorated,
                employee_pension=slip.pension.employee_contribution,
                employer_pension=slip.pension.employer_contribution,
                salary_advance=slip.salary_advance,
                total_deductions=slip.total_deductions,
                net_salary=slip.net_salary,
                employer_cost=slip.employer_cost,
                warnings=",".join(slip.warnings),
            )
        )

    run.lines.all().delete()  # a draft is replaced wholesale
    PayrollLine.objects.bulk_create(lines)
    run.rules_snapshot = found.snapshot
    run.skipped = skipped
    run.calculated_at = timezone.now()
    run.calculated_by = user
    run.save()

    totals = run_totals(run)
    record(
        "payroll.calculated",
        obj=run,
        actor=user,
        changes={
            "employees": len(lines),
            "skipped": len(skipped),
            "net_total": str(totals.net_salary),
        },
    )
    return run


@dataclass(frozen=True)
class Totals:
    employees: int
    gross_earnings: Decimal
    paye: Decimal
    employee_pension: Decimal
    employer_pension: Decimal
    salary_advance: Decimal
    net_salary: Decimal
    employer_cost: Decimal


def run_totals(run: PayrollRun) -> Totals:
    agg = run.lines.aggregate(
        employees=Count("id"),
        gross=Sum("gross_earnings"),
        paye=Sum("paye"),
        ee=Sum("employee_pension"),
        er=Sum("employer_pension"),
        advance=Sum("salary_advance"),
        net=Sum("net_salary"),
        cost=Sum("employer_cost"),
    )
    zero = money(0)
    return Totals(
        employees=agg["employees"],
        gross_earnings=agg["gross"] or zero,
        paye=agg["paye"] or zero,
        employee_pension=agg["ee"] or zero,
        employer_pension=agg["er"] or zero,
        salary_advance=agg["advance"] or zero,
        net_salary=agg["net"] or zero,
        employer_cost=agg["cost"] or zero,
    )


def _digest(run: PayrollRun) -> str:
    rows = run.lines.values_list(
        "employee_number",
        "gross_earnings",
        "paye",
        "employee_pension",
        "employer_pension",
        "salary_advance",
        "net_salary",
    )
    return lines_digest(run.period.label, rows)


def _transition(run: PayrollRun, user, permission: str, expected, new, action: str, **fields):
    _require(user, permission)
    with transaction.atomic():
        fresh = PayrollRun.objects.select_for_update().get(pk=run.pk)
        if fresh.status != expected:
            raise PayrollStateError(
                f"{fresh.period.label} is {fresh.get_status_display().lower()}; "
                f"this needs it to be {PayrollRun.Status(expected).label.lower()}."
            )
        fresh.status = new
        for name, value in fields.items():
            setattr(fresh, name, value)
        fresh.save()
        record(action, obj=fresh, actor=user, changes={"status": {"old": expected, "new": new}})
    return fresh


def submit_for_review(run: PayrollRun, user) -> PayrollRun:
    if not run.lines.exists():
        raise PayrollStateError("There is nothing to review: no employees were calculated.")
    return _transition(
        run, user, CALCULATE, PayrollRun.Status.DRAFT, PayrollRun.Status.REVIEW,
        "payroll.submitted", submitted_at=timezone.now(), submitted_by=user,
    )


def return_to_draft(run: PayrollRun, user) -> PayrollRun:
    return _transition(
        run, user, CALCULATE, PayrollRun.Status.REVIEW, PayrollRun.Status.DRAFT,
        "payroll.returned_to_draft", submitted_at=None, submitted_by=None,
    )


def lock_run(run: PayrollRun, user, password: str) -> PayrollRun:
    """Final approval. Needs the lock permission and the user's own password again."""
    _require(user, LOCK)
    if not password or not user.check_password(password):
        record("payroll.lock_refused", obj=run, actor=user, changes={"reason": "wrong password"})
        raise PasswordConfirmationError("The password was not correct. The payroll was not locked.")
    with transaction.atomic():
        fresh = PayrollRun.objects.select_for_update().get(pk=run.pk)
        if fresh.status != PayrollRun.Status.REVIEW:
            raise PayrollStateError(
                f"{fresh.period.label} must be in review to be locked "
                f"(it is {fresh.get_status_display().lower()})."
            )
        digest = _digest(fresh)
        totals = run_totals(fresh)
        fresh.status = PayrollRun.Status.LOCKED
        fresh.locked_at = timezone.now()
        fresh.locked_by = user
        fresh.digest = digest
        fresh.save()
        record(
            "payroll.locked",
            obj=fresh,
            actor=user,
            changes={
                "employees": totals.employees,
                "net_total": str(totals.net_salary),
                "digest": digest,
            },
        )
    return fresh


def verify_run(run: PayrollRun) -> bool:
    """True if a locked payroll's figures still match their fingerprint."""
    return run.is_locked and bool(run.digest) and _digest(run) == run.digest
