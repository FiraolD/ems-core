"""Payslip PDFs, report downloads and employee self-service (needs Django)."""
import io
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")
pytest.importorskip("reportlab")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.management import call_command  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from core.extensions.registry import registry  # noqa: E402
from modules.hr.models import Employee, SalaryRecord  # noqa: E402
from modules.payroll import service  # noqa: E402
from modules.payroll.models import PayrollLine  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"
D = Decimal

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_hooks():
    registry.clear()
    yield
    registry.clear()


@pytest.fixture
def roles():
    call_command("sync_roles", "--strict", stdout=io.StringIO())


def user_with_role(role, name=None):
    user = User.objects.create_user(name or role, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


def make_employee(number, basic, user=None):
    employee = Employee.objects.create(
        employee_number=number, full_name=f"Person {number}", employment_date=date(2020, 1, 1), user=user
    )
    SalaryRecord.objects.create(employee=employee, effective_date=date(2020, 1, 1), basic_salary=D(basic))
    return employee


@pytest.fixture
def world(roles):
    me = user_with_role("employee", "me")
    other = user_with_role("employee", "other")
    make_employee("E1", "10000", user=me)
    make_employee("E2", "5000", user=other)
    officer = user_with_role("payroll_officer")
    approver = user_with_role("admin")
    run = service.calculate_run(2026, 9, officer)
    return {"me": me, "other": other, "officer": officer, "approver": approver, "run": run}


def lock(world):
    run = service.submit_for_review(world["run"], world["officer"])
    return service.lock_run(run, world["approver"], PASSWORD)


def pdf_ok(response):
    return response.status_code == 200 and response.content.startswith(b"%PDF")


# --- Staff downloads -------------------------------------------------------------------


def test_payroll_officer_can_download_payslips_and_they_are_audited(client, world):
    client.force_login(world["officer"])
    assert pdf_ok(client.get("/payroll/2026/9/payslips.pdf"))
    line = PayrollLine.objects.get(employee_number="E1")
    assert pdf_ok(client.get(f"/payroll/payslip/{line.pk}.pdf"))
    assert AuditEvent.objects.filter(action="payroll.payslips_exported").exists()
    assert AuditEvent.objects.filter(action="payroll.payslip_viewed").exists()


def test_a_draft_payroll_downloads_are_marked_draft(client, world):
    client.force_login(world["officer"])
    response = client.get("/payroll/2026/9/payslips.pdf")
    assert "DRAFT" in response["Content-Disposition"]
    assert "private" in response["Cache-Control"]


def test_reports_download_as_csv_and_are_audited(client, world):
    client.force_login(world["officer"])
    for key in ("register", "income-tax", "pension"):
        response = client.get(f"/payroll/2026/9/report/{key}.csv")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert "Employee No." in response.content.decode("utf-8-sig")
    assert AuditEvent.objects.filter(action="payroll.report_exported").count() == 3


def test_unknown_report_is_404(client, world):
    client.force_login(world["officer"])
    assert client.get("/payroll/2026/9/report/nonsense.csv").status_code == 404


def test_bank_transfer_list_needs_a_locked_payroll(client, world):
    client.force_login(world["officer"])
    response = client.get("/payroll/2026/9/report/bank-transfer.csv")
    assert response.status_code == 302
    lock(world)
    response = client.get("/payroll/2026/9/report/bank-transfer.csv")
    assert response.status_code == 200
    assert "DRAFT" not in response["Content-Disposition"]


def test_ordinary_employees_cannot_use_staff_downloads(client, world):
    client.force_login(world["me"])
    line = PayrollLine.objects.get(employee_number="E2")
    assert client.get("/payroll/2026/9/payslips.pdf").status_code == 403
    assert client.get(f"/payroll/payslip/{line.pk}.pdf").status_code == 403
    assert client.get("/payroll/2026/9/report/register.csv").status_code == 403


def test_downloads_need_sign_in(client, world):
    assert client.get("/payroll/2026/9/payslips.pdf").status_code == 302


# --- Self-service ----------------------------------------------------------------------


def test_my_payslips_is_empty_until_the_payroll_is_locked(client, world):
    client.force_login(world["me"])
    page = client.get("/payroll/my/")
    assert page.status_code == 200
    assert "No approved payslips yet" in page.content.decode()


def test_my_payslips_lists_only_my_locked_months_and_downloads(client, world):
    lock(world)
    client.force_login(world["me"])
    page = client.get("/payroll/my/").content.decode()
    assert "September 2026" in page
    mine = PayrollLine.objects.get(employee_number="E1")
    response = client.get(f"/payroll/my/{mine.pk}.pdf")
    assert pdf_ok(response)
    assert "DRAFT" not in response["Content-Disposition"]


def test_nobody_can_open_someone_elses_payslip(client, world):
    lock(world)
    theirs = PayrollLine.objects.get(employee_number="E2")
    client.force_login(world["me"])
    assert client.get(f"/payroll/my/{theirs.pk}.pdf").status_code == 404


def test_an_unapproved_payslip_is_not_available_to_the_employee(client, world):
    mine = PayrollLine.objects.get(employee_number="E1")
    client.force_login(world["me"])
    assert client.get(f"/payroll/my/{mine.pk}.pdf").status_code == 404


def test_a_sign_in_without_an_employee_record_sees_a_message(client, world, roles):
    client.force_login(user_with_role("employee", "unlinked"))
    page = client.get("/payroll/my/")
    assert page.status_code == 200
    assert "not linked" in page.content.decode()
    mine = PayrollLine.objects.get(employee_number="E1")
    assert client.get(f"/payroll/my/{mine.pk}.pdf").status_code == 404


def test_run_page_shows_download_links_to_staff(client, world):
    client.force_login(world["officer"])
    page = client.get("/payroll/2026/9/").content.decode()
    assert "All payslips (PDF)" in page
    assert "Bank transfer list" not in page  # only once locked
