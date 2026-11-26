"""Attendance, leave and overtime feeding payroll, and the locked-month guard (needs Django).

Worked by hand for September 2026 (30-day month), basic 12000, transport 600, default rules:
  attendance: absent Wed 2 Sep, half day Thu 3 Sep, absent Tue 15 Sep
  approved annual leave Mon 14 - Wed 16 Sep (3 days; excuses the absence on the 15th)
  approved overtime: 2h ordinary (x1.25) Tue 8 Sep + 3h rest day (x2.0) Sun 13 Sep
  unpaid days 1.5 -> basic deduction 12000/30 x 1.5 = 600
  transport deduction 600/30 x (1.5 + 3) = 90 -> transport 510
  overtime 12000/240 = 50/h x (2x1.25 + 3x2.0 = 8.5) = 425
  gross 12000 + 510 + 425 = 12935; taxable 12935 - 600 = 12335; PAYE 12335 x 30% - 1350 = 2350.50
  pension 7% x (12000 - 600) = 798; net 12935 - 600 - 2350.50 - 798 = 9186.50
"""
import io
from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.management import call_command  # noqa: E402

from core import period_lock  # noqa: E402
from core.extensions.registry import registry  # noqa: E402
from modules.attendance import payroll as attendance_payroll  # noqa: E402
from modules.attendance import service as attendance_service  # noqa: E402
from modules.attendance.models import AttendanceRecord, PublicHoliday  # noqa: E402
from modules.hr.models import Employee, SalaryRecord  # noqa: E402
from modules.leave import payroll as leave_payroll  # noqa: E402
from modules.leave import service as leave_service  # noqa: E402
from modules.leave.models import LeaveRequest, LeaveType  # noqa: E402
from modules.overtime import payroll as overtime_payroll  # noqa: E402
from modules.overtime import service as overtime_service  # noqa: E402
from modules.overtime.models import OvertimeCategory, OvertimeEntry  # noqa: E402
from modules.payroll import service as payroll_service  # noqa: E402
from modules.payroll.models import PayrollLine  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def hooks():
    registry.clear()
    attendance_payroll.register()
    leave_payroll.register()
    overtime_payroll.register()
    yield
    registry.clear()


@pytest.fixture
def world():
    call_command("sync_roles", "--strict", stdout=io.StringIO())
    call_command("seed_overtime_categories", stdout=io.StringIO())
    emp = Employee.objects.create(employee_number="E1", full_name="Person", employment_date=date(2020, 1, 1))
    SalaryRecord.objects.create(
        employee=emp, effective_date=date(2020, 1, 1), basic_salary=D("12000"), transport_allowance=D("600")
    )
    annual = LeaveType.objects.create(name="Annual leave", pay_code="annual_leave", uses_balance=True, annual_days=30)
    unpaid = LeaveType.objects.create(name="Unpaid leave", pay_code="unpaid_leave")
    return dict(emp=emp, annual=annual, unpaid=unpaid)


def make_user(role, name):
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


def attend(emp, day, status):
    return AttendanceRecord.objects.create(employee=emp, date=day, status=status)


def leave(emp, kind, start, end, days, status="approved", half_day=False):
    return LeaveRequest.objects.create(
        employee=emp, leave_type=kind, start_date=start, end_date=end, days=D(days), status=status, half_day=half_day
    )


def overtime(emp, day, hours, kind, status="approved"):
    cat = OvertimeCategory.objects.get(kind=kind)
    return OvertimeEntry.objects.create(
        employee=emp, work_date=day, hours=D(hours), category=cat, multiplier=cat.multiplier, status=status
    )


def pay_line():
    payroll_service.calculate_run(2026, 9)
    return PayrollLine.objects.get(employee_number="E1")


def test_the_worked_example_flows_into_the_payslip(world):
    emp = world["emp"]
    attend(emp, date(2026, 9, 2), "absent")
    attend(emp, date(2026, 9, 3), "half_day")
    attend(emp, date(2026, 9, 15), "absent")  # excused by the approved leave below
    leave(emp, world["annual"], date(2026, 9, 14), date(2026, 9, 16), 3)
    overtime(emp, date(2026, 9, 8), "2", "normal")
    overtime(emp, date(2026, 9, 13), "3", "rest_day")
    line = pay_line()
    assert (line.unpaid_days, line.paid_leave_days) == (D("1.5"), D("3"))
    assert line.absence_deduction == D("600.00")
    assert line.transport_payable == D("510.00")
    assert line.overtime_pay == D("425.00")
    assert line.gross_earnings == D("12935.00")
    assert line.paye == D("2350.50")
    assert line.employee_pension == D("798.00")
    assert line.net_salary == D("9186.50")


def test_nothing_recorded_means_a_normal_month(world):
    line = pay_line()
    assert (line.unpaid_days, line.paid_leave_days, line.overtime_pay) == (D("0"), D("0"), D("0.00"))
    assert line.gross_earnings == D("12600.00")


def test_only_approved_leave_and_overtime_count(world):
    emp = world["emp"]
    leave(emp, world["annual"], date(2026, 9, 14), date(2026, 9, 16), 3, status="pending")
    leave(emp, world["annual"], date(2026, 9, 21), date(2026, 9, 22), 2, status="rejected")
    overtime(emp, date(2026, 9, 8), "2", "normal", status="pending")
    overtime(emp, date(2026, 9, 9), "2", "normal", status="cancelled")
    line = pay_line()
    assert (line.paid_leave_days, line.overtime_pay) == (D("0"), D("0.00"))


def test_unpaid_leave_deducts_and_half_days_are_handled(world):
    emp = world["emp"]
    leave(emp, world["unpaid"], date(2026, 9, 7), date(2026, 9, 8), 2)  # two unpaid days
    leave(emp, world["unpaid"], date(2026, 9, 9), date(2026, 9, 9), "0.5", half_day=True)  # half unpaid
    leave(emp, world["annual"], date(2026, 9, 10), date(2026, 9, 10), "0.5", half_day=True)  # paid half: no effect
    line = pay_line()
    assert line.unpaid_days == D("2.5")
    assert line.paid_leave_days == D("0")


def test_rest_days_and_holidays_inside_leave_are_not_leave_days(world):
    PublicHoliday.objects.create(date=date(2026, 9, 15), name="Holiday")
    # Fri 11 .. Tue 15: Fri, Sat, Mon work; Sun 13 is the rest day; Tue 15 is a holiday
    leave(world["emp"], world["annual"], date(2026, 9, 11), date(2026, 9, 15), 3)
    assert pay_line().paid_leave_days == D("3")


def test_leave_only_counts_inside_the_month(world):
    leave(world["emp"], world["annual"], date(2026, 8, 28), date(2026, 9, 2), 5)  # Fri 28 Aug .. Wed 2 Sep
    assert pay_line().paid_leave_days == D("2")  # only Tue 1 and Wed 2 Sep fall in September


def test_registering_twice_does_not_double_count(world):
    overtime_payroll.register()
    overtime_payroll.register()
    overtime(world["emp"], date(2026, 9, 8), "2", "normal")  # 2h x 1.25 x 50 = 125
    assert pay_line().overtime_pay == D("125.00")


def test_overtime_without_a_salary_record_is_ignored_not_a_crash(world):
    SalaryRecord.objects.all().delete()
    overtime(world["emp"], date(2026, 9, 8), "2", "normal")
    run = payroll_service.calculate_run(2026, 9)
    assert run.skipped and not PayrollLine.objects.exists()


# --- Locked month ---------------------------------------------------------------------


@pytest.fixture
def locked(world):
    officer, approver = make_user("payroll_officer", "officer"), make_user("admin", "approver")
    run = payroll_service.calculate_run(2026, 9, officer)
    run = payroll_service.submit_for_review(run, officer)
    payroll_service.lock_run(run, approver, PASSWORD)
    return world


def test_a_locked_month_closes_for_attendance(locked):
    with pytest.raises(period_lock.PeriodClosed):
        attend(locked["emp"], date(2026, 9, 20), "absent")
    attend(locked["emp"], date(2026, 10, 5), "absent")  # October is still open


def test_a_locked_month_rejects_an_attendance_import(locked):
    hr = make_user("hr_manager", "hr")
    csv_text = "employee_number,date,status,note\nE1,2026-09-20,absent,\n"
    with pytest.raises(attendance_service.ImportRejected) as caught:
        attendance_service.import_csv(csv_text, hr)
    assert "locked" in " ".join(caught.value.errors)
    assert AttendanceRecord.objects.count() == 0


def test_a_locked_month_closes_for_leave_and_overtime(locked):
    hr = make_user("hr_manager", "hr")
    with pytest.raises(leave_service.LeaveRefused, match="locked"):
        leave_service.request_leave(locked["emp"], locked["annual"], date(2026, 9, 21), date(2026, 9, 22), hr)
    with pytest.raises(overtime_service.OvertimeRefused, match="locked"):
        overtime_service.record_overtime(locked["emp"], date(2026, 9, 21), "2", "normal", hr)


def test_approved_leave_in_a_locked_month_cannot_be_cancelled_and_pending_cannot_be_approved(world):
    hr = make_user("hr_manager", "hr")
    emp, annual = world["emp"], world["annual"]
    pending = leave_service.request_leave(emp, annual, date(2026, 9, 21), date(2026, 9, 22), hr)
    approved = leave(emp, annual, date(2026, 9, 28), date(2026, 9, 29), 2)
    ot = overtime_service.record_overtime(emp, date(2026, 9, 9), "2", "normal", hr)
    officer, approver = make_user("payroll_officer", "officer"), make_user("admin", "approver")
    run = payroll_service.submit_for_review(payroll_service.calculate_run(2026, 9, officer), officer)
    payroll_service.lock_run(run, approver, PASSWORD)
    with pytest.raises(leave_service.LeaveRefused, match="locked"):
        leave_service.decide(pending, hr, approve=True)
    leave_service.decide(pending, hr, approve=False)  # rejecting changes nothing in pay, so it is allowed
    with pytest.raises(leave_service.LeaveRefused, match="locked"):
        leave_service.cancel(approved, hr)
    other_hr = make_user("hr_manager", "hr2")
    with pytest.raises(overtime_service.OvertimeRefused, match="locked"):
        overtime_service.decide(ot, other_hr, approve=True)
