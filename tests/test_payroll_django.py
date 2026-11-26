"""Payroll module: calculation, workflow, locking, permissions and screens.

Expected money was worked out by hand (default Ethiopian rules, September 2026):
  E1  basic 10000 + transport 600: taxable 10600, tax 1830, pension 700 / 1100,
      gross 10600, net 8070, employer cost 11700
  E2  basic 5000: tax 500, pension 350 / 550, gross 5000, net 4150, employer cost 5550
  month: gross 15600, tax 2330, employee pension 1050, employer pension 1650,
         net 12220, employer cost 17250
"""
import io
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.exceptions import PermissionDenied  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import connection  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from core.extensions.registry import registry  # noqa: E402
from core.rules.models import RuleValue  # noqa: E402
from modules.hr.models import Employee, SalaryRecord  # noqa: E402
from modules.payroll import service  # noqa: E402
from modules.payroll.inputs import HOOK  # noqa: E402
from modules.payroll.models import (  # noqa: E402
    Bonus,
    PayrollLine,
    PayrollLocked,
    PayrollRun,
    SalaryAdvance,
)

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"
D = Decimal

pytestmark = pytest.mark.django_db


def make_employee(number, basic, transport="0", hired=date(2020, 1, 1), **extra):
    employee = Employee.objects.create(
        employee_number=number, full_name=f"Person {number}", employment_date=hired, **extra
    )
    SalaryRecord.objects.create(
        employee=employee,
        effective_date=hired,
        basic_salary=D(basic),
        transport_allowance=D(transport),
    )
    return employee


@pytest.fixture
def staff():
    e1 = make_employee("E1", "10000", "600")
    e2 = make_employee("E2", "5000")
    return e1, e2


@pytest.fixture
def roles():
    call_command("sync_roles", "--strict", stdout=io.StringIO())


def user_with_role(role, name=None):
    user = User.objects.create_user(name or role, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def officer(roles):
    return user_with_role("payroll_officer")


@pytest.fixture
def approver(roles):
    return user_with_role("admin")


@pytest.fixture(autouse=True)
def clean_hooks():
    registry.clear()
    yield
    registry.clear()


def line(run, number):
    return PayrollLine.objects.get(run=run, employee_number=number)


# --- Calculation ---------------------------------------------------------------------


def test_a_month_is_calculated_with_the_expected_figures(staff, officer):
    run = service.calculate_run(2026, 9, officer)
    assert run.status == "draft"
    e1, e2 = line(run, "E1"), line(run, "E2")
    assert (e1.gross_earnings, e1.paye, e1.employee_pension, e1.net_salary) == (
        D("10600.00"), D("1830.00"), D("700.00"), D("8070.00"),
    )
    assert (e1.employer_pension, e1.employer_cost) == (D("1100.00"), D("11700.00"))
    assert (e2.gross_earnings, e2.paye, e2.net_salary, e2.employer_cost) == (
        D("5000.00"), D("500.00"), D("4150.00"), D("5550.00"),
    )
    totals = service.run_totals(run)
    assert totals.employees == 2
    assert totals.gross_earnings == D("15600.00")
    assert totals.paye == D("2330.00")
    assert totals.employee_pension == D("1050.00")
    assert totals.employer_pension == D("1650.00")
    assert totals.net_salary == D("12220.00")
    assert totals.employer_cost == D("17250.00")


def test_totals_always_show_santims_even_when_empty_or_round(officer):
    empty = service.run_totals(service.calculate_run(2026, 9, officer))
    assert empty.employees == 0
    for value in (empty.gross_earnings, empty.paye, empty.net_salary, empty.employer_cost):
        assert str(value) == "0.00"
    make_employee("ROUND", "10000")
    full = service.run_totals(service.calculate_run(2026, 9, officer))
    assert str(full.gross_earnings) == "10000.00"  # not "10000"


def test_the_run_keeps_the_rules_it_was_calculated_with(staff, officer):
    run = service.calculate_run(2026, 9, officer)
    assert run.rules_snapshot["pension_employee_rate"] == "0.07"
    assert run.rules_snapshot["tax_brackets"][-1]["rate"] == "0.35"
    assert run.calculated_by == officer and run.calculated_at is not None


def test_lines_keep_who_the_employee_was(staff, officer):
    e1, _ = staff
    run = service.calculate_run(2026, 9, officer)
    e1.full_name = "Renamed Later"
    e1.save()
    assert line(run, "E1").employee_name == "Person E1"


def test_recalculating_replaces_the_lines_and_picks_up_changes(staff, officer):
    e1, _ = staff
    service.calculate_run(2026, 9, officer)
    SalaryRecord.objects.create(employee=e1, effective_date=date(2026, 9, 1), basic_salary=D("12000"))
    run = service.calculate_run(2026, 9, officer)
    assert run.lines.count() == 2
    assert line(run, "E1").basic_salary == D("12000.00")


def test_only_people_due_pay_are_included_and_the_rest_are_listed_or_left_out(officer):
    make_employee("OK", "5000")
    make_employee("SUSP", "5000", status="suspended")
    make_employee("FUTURE", "5000", hired=date(2026, 10, 5))
    make_employee("GONE", "5000", status="resigned", termination_date=date(2026, 8, 31))
    nosalary = Employee.objects.create(
        employee_number="NOPAY", full_name="No Salary", employment_date=date(2020, 1, 1)
    )
    run = service.calculate_run(2026, 9, officer)
    assert list(run.lines.values_list("employee_number", flat=True)) == ["OK"]
    assert run.skipped == [
        {
            "employee_number": nosalary.employee_number,
            "name": "No Salary",
            "reason": "No salary record applies to September 2026.",
        }
    ]


def test_approved_bonus_is_paid_and_taxed_and_unapproved_is_ignored(staff, officer):
    _, e2 = staff
    Bonus.objects.create(employee=e2, year=2026, month=9, amount=D("1000"), approved=True)
    Bonus.objects.create(employee=e2, year=2026, month=9, amount=D("9999"), approved=False)
    Bonus.objects.create(employee=e2, year=2026, month=8, amount=D("7777"), approved=True)
    run = service.calculate_run(2026, 9, officer)
    row = line(run, "E2")
    # taxable 6000 -> 6000 x 20% - 500 = 700; the bonus' share is 700 - 500 = 200
    assert (row.bonus, row.gross_earnings, row.paye, row.bonus_tax) == (
        D("1000.00"), D("6000.00"), D("700.00"), D("200.00"),
    )
    assert row.net_salary == D("4950.00")  # 6000 - 700 - 350


def test_advances_are_deducted_only_in_their_own_month(staff, officer):
    _, e2 = staff
    SalaryAdvance.objects.create(employee=e2, year=2026, month=9, amount=D("400"))
    SalaryAdvance.objects.create(employee=e2, year=2026, month=10, amount=D("999"))
    run = service.calculate_run(2026, 9, officer)
    assert line(run, "E2").salary_advance == D("400.00")
    assert line(run, "E2").net_salary == D("3750.00")  # 4150 - 400


def test_other_modules_can_add_inputs_through_the_hook(staff, officer):
    @registry.hook(HOOK)
    def overtime(inputs, *, employee, **kwargs):
        if employee.employee_number == "E2":
            inputs.overtime_pay += D("500")
        return inputs

    row = line(service.calculate_run(2026, 9, officer), "E2")
    # taxable 5500 -> 5500 x 20% - 500 = 600
    assert (row.overtime_pay, row.gross_earnings, row.paye, row.net_salary) == (
        D("500.00"), D("5500.00"), D("600.00"), D("4550.00"),
    )


def test_a_mid_month_hire_is_paid_from_the_hire_date(officer):
    make_employee("NEW", "9000", hired=date(2026, 9, 16))
    row = line(service.calculate_run(2026, 9, officer), "NEW")
    assert (row.days_worked, row.basic_earned) == (15, D("4500.00"))
    assert row.pension_prorated is True and row.employee_pension == D("315.00")


def test_a_rule_set_in_the_system_applies_from_its_start_date(staff, officer):
    RuleValue.objects.create(key="transport_taxable", value="no", effective_from=date(2026, 10, 1))
    september = line(service.calculate_run(2026, 9, officer), "E1")
    october = line(service.calculate_run(2026, 10, officer), "E1")
    assert (september.paye, september.net_salary) == (D("1830.00"), D("8070.00"))
    # October: taxable 10000 -> 10000 x 25% - 850 = 1650; net 10600 - 1650 - 700
    assert (october.paye, october.net_salary) == (D("1650.00"), D("8250.00"))


def test_leavers_are_prorated_unless_the_system_rule_says_otherwise(officer):
    make_employee("LEFT", "9000", status="resigned", termination_date=date(2026, 9, 20))
    row = line(service.calculate_run(2026, 9, officer), "LEFT")
    assert (row.days_worked, row.basic_earned) == (20, D("6000.00"))
    RuleValue.objects.create(key="prorate_leavers", value="no", effective_from=date(2026, 1, 1))
    row = line(service.calculate_run(2026, 9, officer), "LEFT")
    assert (row.days_worked, row.basic_earned) == (None, D("9000.00"))


def test_a_raise_pays_from_the_next_month(officer):
    employee = make_employee("R1", "5000")
    SalaryRecord.objects.create(employee=employee, effective_date=date(2026, 9, 15), basic_salary=D("6000"))
    assert line(service.calculate_run(2026, 9, officer), "R1").basic_salary == D("5000.00")
    assert line(service.calculate_run(2026, 10, officer), "R1").basic_salary == D("6000.00")


def test_a_raise_dated_the_first_pays_that_month(officer):
    employee = make_employee("R2", "5000")
    SalaryRecord.objects.create(employee=employee, effective_date=date(2026, 10, 1), basic_salary=D("6000"))
    assert line(service.calculate_run(2026, 9, officer), "R2").basic_salary == D("5000.00")
    assert line(service.calculate_run(2026, 10, officer), "R2").basic_salary == D("6000.00")


def test_a_bad_month_is_refused(officer):
    for year, month in [(1999, 9), (2026, 0), (2026, 13)]:
        with pytest.raises(service.PayrollError):
            service.calculate_run(year, month, officer)


def test_calculation_is_audited(staff, officer):
    run = service.calculate_run(2026, 9, officer)
    event = AuditEvent.objects.get(action="payroll.calculated")
    assert event.object_id == str(run.pk) and event.actor_username == officer.username
    assert event.changes == {"employees": 2, "skipped": 0, "net_total": "12220.00"}


def test_the_command_calculates_a_month(staff):
    out = io.StringIO()
    call_command("calculate_payroll", "2026", "9", stdout=out)
    assert "2 employees" in out.getvalue() and "12220.00" in out.getvalue()


# --- Workflow ------------------------------------------------------------------------


def test_the_full_path_draft_review_locked(staff, officer, approver):
    run = service.calculate_run(2026, 9, officer)
    run = service.submit_for_review(run, officer)
    assert run.status == "review" and run.submitted_by == officer
    run = service.lock_run(run, approver, PASSWORD)
    assert run.status == "locked" and run.locked_by == approver and run.locked_at
    assert len(run.digest) == 64 and service.verify_run(run)
    locked = AuditEvent.objects.get(action="payroll.locked")
    assert locked.changes["digest"] == run.digest
    assert locked.actor_username == "admin" and locked.actor_id == approver.pk


def test_each_step_is_audited(staff, officer, approver):
    run = service.calculate_run(2026, 9, officer)
    service.submit_for_review(run, officer)
    service.return_to_draft(run, officer)
    service.submit_for_review(run, officer)
    service.lock_run(run, approver, PASSWORD)
    actions = list(
        AuditEvent.objects.filter(action__startswith="payroll.").order_by("id").values_list("action", flat=True)
    )
    assert actions == [
        "payroll.calculated",
        "payroll.submitted",
        "payroll.returned_to_draft",
        "payroll.submitted",
        "payroll.locked",
    ]


def test_nothing_to_review_cannot_be_submitted(officer):
    run = service.calculate_run(2026, 9, officer)
    with pytest.raises(service.PayrollStateError, match="nothing to review"):
        service.submit_for_review(run, officer)


def test_steps_must_happen_in_order(staff, officer, approver):
    run = service.calculate_run(2026, 9, officer)
    with pytest.raises(service.PayrollStateError):
        service.lock_run(run, approver, PASSWORD)  # still a draft
    with pytest.raises(service.PayrollStateError):
        service.return_to_draft(run, officer)  # nothing to return
    service.submit_for_review(run, officer)
    with pytest.raises(service.PayrollStateError):
        service.submit_for_review(run, officer)  # already in review
    with pytest.raises(service.PayrollStateError):
        service.calculate_run(2026, 9, officer)  # no recalculating while in review


def test_a_wrong_password_does_not_lock_and_is_recorded(staff, officer, approver):
    run = service.calculate_run(2026, 9, officer)
    service.submit_for_review(run, officer)
    for wrong in ("", "nope"):
        with pytest.raises(service.PasswordConfirmationError):
            service.lock_run(run, approver, wrong)
    assert PayrollRun.objects.get(pk=run.pk).status == "review"
    assert AuditEvent.objects.filter(action="payroll.lock_refused").count() == 2


def test_only_the_right_people_can_do_each_step(staff, roles, officer, approver):
    hr = user_with_role("hr_manager")
    with pytest.raises(PermissionDenied):
        service.calculate_run(2026, 9, hr)
    run = service.calculate_run(2026, 9, officer)
    service.submit_for_review(run, officer)
    with pytest.raises(PermissionDenied):
        service.lock_run(run, officer, PASSWORD)  # the preparer cannot approve
    with pytest.raises(PermissionDenied):
        service.return_to_draft(run, approver)  # the approver does not prepare
    with pytest.raises(PermissionDenied):
        service.submit_for_review(run, None)


def test_a_locked_payroll_cannot_be_changed_in_any_way(staff, officer, approver):
    run = service.lock_run(
        service.submit_for_review(service.calculate_run(2026, 9, officer), officer), approver, PASSWORD
    )
    for step in (
        lambda: service.calculate_run(2026, 9, officer),
        lambda: service.submit_for_review(run, officer),
        lambda: service.return_to_draft(run, officer),
    ):
        with pytest.raises(service.PayrollError):
            step()
    row = line(run, "E1")
    row.net_salary = D("1")
    with pytest.raises(PayrollLocked):
        row.save()
    with pytest.raises(PayrollLocked):
        row.delete()
    with pytest.raises(PayrollLocked):
        PayrollLine.objects.filter(run=run).update(net_salary=1)
    with pytest.raises(PayrollLocked):
        PayrollLine.objects.filter(run=run).delete()
    with pytest.raises(PayrollLocked):
        PayrollRun.objects.get(pk=run.pk).delete()
    reloaded = PayrollRun.objects.get(pk=run.pk)
    reloaded.status = "draft"
    with pytest.raises(PayrollLocked):
        reloaded.save()
    assert PayrollRun.objects.get(pk=run.pk).status == "locked"
    assert line(run, "E1").net_salary == D("8070.00")


def test_changes_made_underneath_the_application_are_detected(staff, officer, approver):
    run = service.lock_run(
        service.submit_for_review(service.calculate_run(2026, 9, officer), officer), approver, PASSWORD
    )
    assert service.verify_run(run)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE payroll_payrollline SET net_salary = 1 WHERE employee_number = %s", ["E1"])
    assert service.verify_run(PayrollRun.objects.get(pk=run.pk)) is False


def test_a_draft_is_not_verified(staff, officer):
    assert service.verify_run(service.calculate_run(2026, 9, officer)) is False


# --- Screens -------------------------------------------------------------------------


def test_screens_need_sign_in_and_permission(client, staff, roles):
    assert client.get("/payroll/").status_code == 302
    client.force_login(user_with_role("hr_manager"))
    assert client.get("/payroll/").status_code == 403
    client.force_login(user_with_role("employee"))
    assert client.get("/payroll/").status_code == 403


def test_a_payroll_officer_calculates_and_views_a_month(client, staff, officer):
    client.force_login(officer)
    assert client.get("/payroll/").status_code == 200
    response = client.post("/payroll/calculate/", {"year": "2026", "month": "9"})
    assert response.status_code == 302 and response.url == "/payroll/2026/9/"
    page = client.get("/payroll/2026/9/")
    html = page.content.decode()
    assert page.status_code == 200
    assert "September 2026" in html and "Person E1" in html and "12220.00" in html
    assert "Submit for review" in html and "Approve and lock" not in html


def test_calculating_with_bad_input_shows_a_message_not_an_error(client, officer):
    client.force_login(officer)
    response = client.post("/payroll/calculate/", {"year": "abc", "month": "9"}, follow=True)
    assert response.status_code == 200
    assert "Choose a year and a month" in response.content.decode()


def test_calculating_needs_the_calculate_permission(client, staff, roles):
    client.force_login(user_with_role("auditor"))
    assert client.post("/payroll/calculate/", {"year": "2026", "month": "9"}).status_code == 403


def test_locking_through_the_screens_needs_the_password(client, staff, officer, approver):
    client.force_login(officer)
    client.post("/payroll/calculate/", {"year": "2026", "month": "9"})
    client.post("/payroll/2026/9/submit/")
    client.force_login(approver)
    page = client.get("/payroll/2026/9/").content.decode()
    assert "Approve and lock" in page and "Submit for review" not in page

    wrong = client.post("/payroll/2026/9/lock/", {"password": "nope"}, follow=True)
    assert "password was not correct" in wrong.content.decode()
    assert PayrollRun.objects.get().status == "review"

    right = client.post("/payroll/2026/9/lock/", {"password": PASSWORD}, follow=True)
    assert "is locked" in right.content.decode()
    assert PayrollRun.objects.get().status == "locked"
    assert "verified" in client.get("/payroll/2026/9/").content.decode()


def test_actions_must_be_posted_and_known(client, staff, officer):
    client.force_login(officer)
    client.post("/payroll/calculate/", {"year": "2026", "month": "9"})
    assert client.get("/payroll/2026/9/submit/").status_code == 405
    response = client.post("/payroll/2026/9/explode/", follow=True)
    assert "Unknown action" in response.content.decode()


def test_the_officer_cannot_lock_through_the_screens(client, staff, officer):
    client.force_login(officer)
    client.post("/payroll/calculate/", {"year": "2026", "month": "9"})
    client.post("/payroll/2026/9/submit/")
    assert client.post("/payroll/2026/9/lock/", {"password": PASSWORD}).status_code == 403
    assert PayrollRun.objects.get().status == "review"


def test_a_month_that_was_never_calculated_is_not_found(client, officer):
    client.force_login(officer)
    assert client.get("/payroll/2026/9/").status_code == 404


# --- Roles ---------------------------------------------------------------------------


def test_nobody_is_granted_delete_on_payroll(roles):
    for role in ("admin", "payroll_officer", "auditor", "hr_manager"):
        user = user_with_role(role, f"{role}-x")
        for model in ("payrollrun", "payrollline", "payrollperiod", "salaryadvance", "bonus"):
            assert not user.has_perm(f"payroll.delete_{model}")


def test_payroll_results_cannot_be_edited_in_admin(client, staff, officer):
    superuser = User.objects.create_superuser("root", "r@example.com", PASSWORD)
    run = service.calculate_run(2026, 9, officer)
    client.force_login(superuser)
    assert client.get(f"/admin/payroll/payrollrun/{run.pk}/change/").status_code in (200, 302)
    assert client.get("/admin/payroll/payrollrun/add/").status_code == 403
    assert client.post(f"/admin/payroll/payrollrun/{run.pk}/delete/", {"post": "yes"}).status_code == 403
    assert PayrollRun.objects.filter(pk=run.pk).exists()


# --- Look and navigation -------------------------------------------------------------


def test_payroll_pages_use_the_shared_layout_and_their_stylesheet(client, staff, officer):
    client.force_login(officer)
    service.calculate_run(2026, 9, officer)
    for url in ("/payroll/", "/payroll/2026/9/"):
        html = client.get(url).content.decode()
        assert 'href="/static/company/app.css"' in html  # the shared layout
        assert 'href="/static/company/pages.css"' in html  # the shared page styles


def test_home_links_to_payroll_only_for_people_who_may_see_it(client, roles, officer):
    client.force_login(officer)
    assert 'href="/payroll/"' in client.get("/").content.decode()
    client.force_login(user_with_role("employee", "plain"))
    assert "Open payroll" not in client.get("/").content.decode()
