"""HR models, role grants and admin screens."""
import io
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.exceptions import ValidationError  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import IntegrityError, transaction  # noqa: E402
from django.db.models import ProtectedError  # noqa: E402
from django.urls import reverse  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from modules.hr.models import Branch, Department, Employee, Position, SalaryRecord  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"

pytestmark = pytest.mark.django_db


def make_employee(number="E001", **overrides):
    values = {
        "employee_number": number,
        "full_name": "Abebe Kebede",
        "employment_date": date(2024, 1, 15),
    }
    values.update(overrides)
    return Employee.objects.create(**values)


def raise_to(employee, effective, basic, **extra):
    return SalaryRecord.objects.create(
        employee=employee, effective_date=effective, basic_salary=Decimal(basic), **extra
    )


# --- Organisation --------------------------------------------------------------------


def test_blank_codes_do_not_collide():
    Department.objects.create(name="Finance", code="")
    Department.objects.create(name="Sales", code="")
    Branch.objects.create(name="Adama", code="")
    Branch.objects.create(name="Hawassa", code="")
    assert Department.objects.filter(code__isnull=True).count() == 2


def test_real_codes_stay_unique():
    Department.objects.create(name="Finance", code="FIN")
    with pytest.raises(IntegrityError), transaction.atomic():
        Department.objects.create(name="Finance 2", code="FIN")


def test_a_department_in_use_cannot_be_deleted():
    dept = Department.objects.create(name="Finance")
    make_employee(department=dept)
    with pytest.raises(ProtectedError):
        dept.delete()


# --- Employee ------------------------------------------------------------------------


def test_employee_defaults():
    employee = make_employee()
    assert employee.status == "active" and employee.employment_type == "permanent"
    assert employee.is_working
    assert str(employee) == "Abebe Kebede (E001)"


def test_employee_number_is_unique():
    make_employee("E001")
    with pytest.raises(IntegrityError), transaction.atomic():
        make_employee("E001", full_name="Someone Else")


def test_a_leaver_needs_a_leaving_date():
    employee = make_employee(status="resigned")
    with pytest.raises(ValidationError) as error:
        employee.full_clean()
    assert "termination_date" in error.value.message_dict


def test_leaving_before_hiring_is_rejected_by_the_form_and_the_database():
    # The form check: an unsaved employee who "left" before being hired.
    unsaved = Employee(
        employee_number="E009",
        full_name="Backwards Dates",
        employment_date=date(2024, 1, 15),
        status="resigned",
        termination_date=date(2023, 1, 1),
    )
    with pytest.raises(ValidationError) as error:
        unsaved.full_clean()
    assert "termination_date" in error.value.message_dict
    # The database check: refuses the same thing even if the form check is bypassed.
    with pytest.raises(IntegrityError), transaction.atomic():
        unsaved.save()
    employee = make_employee()
    with pytest.raises(IntegrityError), transaction.atomic():
        Employee.objects.filter(pk=employee.pk).update(termination_date=date(2020, 1, 1))


def test_birth_after_hiring_is_rejected():
    employee = make_employee(date_of_birth=date(2025, 1, 1))
    with pytest.raises(ValidationError) as error:
        employee.full_clean()
    assert "date_of_birth" in error.value.message_dict


def test_a_valid_leaver_passes():
    employee = make_employee(status="retired", termination_date=date(2026, 2, 1))
    employee.full_clean()
    assert not employee.is_working


def test_eligible_for_period_uses_the_rules():
    employee = make_employee(status="resigned", termination_date=date(2026, 2, 10))
    assert not employee.eligible_for_period(date(2026, 3, 1), date(2026, 3, 31))
    assert employee.eligible_for_period(date(2026, 2, 1), date(2026, 2, 28))


def test_an_employee_can_be_linked_to_a_user_once():
    user = User.objects.create_user("abebe", password=PASSWORD)
    make_employee("E001", user=user)
    assert user.employee.employee_number == "E001"
    with pytest.raises(IntegrityError), transaction.atomic():
        make_employee("E002", user=user)


# --- Salary history ------------------------------------------------------------------


def test_salary_on_picks_the_record_in_force():
    employee = make_employee()
    raise_to(employee, date(2024, 1, 15), "10000")
    raise_to(employee, date(2025, 1, 1), "12000")
    raise_to(employee, date(2026, 7, 1), "15000")
    assert employee.salary_on(date(2024, 6, 30)).basic_salary == Decimal("10000.00")
    assert employee.salary_on(date(2026, 3, 31)).basic_salary == Decimal("12000.00")
    assert employee.salary_on(date(2026, 7, 1)).basic_salary == Decimal("15000.00")


def test_salary_on_before_any_record_is_none():
    employee = make_employee()
    raise_to(employee, date(2025, 1, 1), "10000")
    assert employee.salary_on(date(2024, 12, 31)) is None


def test_a_future_raise_does_not_apply_yet():
    employee = make_employee()
    raise_to(employee, date(2024, 1, 15), "10000")
    raise_to(employee, date(2999, 1, 1), "99999")
    assert employee.current_salary.basic_salary == Decimal("10000.00")


def test_one_salary_per_employee_per_date():
    employee = make_employee()
    raise_to(employee, date(2025, 1, 1), "10000")
    with pytest.raises(IntegrityError), transaction.atomic():
        raise_to(employee, date(2025, 1, 1), "11000")


def test_negative_pay_is_refused_by_validation_and_the_database():
    employee = make_employee()
    record = SalaryRecord(employee=employee, effective_date=date(2025, 1, 1), basic_salary=-1)
    with pytest.raises(ValidationError):
        record.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        record.save()


def test_gross_adds_all_pay_parts():
    employee = make_employee()
    record = raise_to(
        employee, date(2025, 1, 1), "10000.50", transport_allowance=Decimal("500"),
        other_allowances=Decimal("250.25"),
    )
    assert record.gross == Decimal("10750.75")


def test_salary_history_goes_with_the_employee_only_when_the_employee_is_deleted():
    employee = make_employee()
    raise_to(employee, date(2025, 1, 1), "10000")
    employee.delete()
    assert SalaryRecord.objects.count() == 0


# --- Audit ---------------------------------------------------------------------------


def test_salary_changes_are_audited_with_old_and_new_values():
    employee = make_employee()
    record = raise_to(employee, date(2025, 1, 1), "10000")
    record.basic_salary = Decimal("12000")
    record.save()
    event = AuditEvent.objects.filter(
        action="update", object_type="hr.SalaryRecord", object_id=str(record.pk)
    ).get()
    assert event.changes == {"basic_salary": {"old": "10000.00", "new": "12000.00"}}


def test_employee_edits_are_audited_but_timestamps_are_not():
    employee = make_employee()
    employee.bank_account_number = "1000123456789"
    employee.save()
    event = AuditEvent.objects.get(action="update", object_type="hr.Employee")
    assert set(event.changes) == {"bank_account_number"}


# --- Roles ---------------------------------------------------------------------------


@pytest.fixture
def roles():
    call_command("sync_roles", "--strict", stdout=io.StringIO())


def user_with_role(role, name="u"):
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


def test_hr_manager_can_view_add_and_change_but_not_delete(roles):
    user = user_with_role("hr_manager")
    for model in ("employee", "salaryrecord", "department", "branch", "position"):
        assert user.has_perm(f"hr.view_{model}")
        assert user.has_perm(f"hr.add_{model}")
        assert user.has_perm(f"hr.change_{model}")
        assert not user.has_perm(f"hr.delete_{model}")


def test_payroll_officer_and_auditor_are_read_only(roles):
    for role in ("payroll_officer", "auditor"):
        user = user_with_role(role, role)
        assert user.has_perm("hr.view_employee") and user.has_perm("hr.view_salaryrecord")
        assert not user.has_perm("hr.change_employee")
        assert not user.has_perm("hr.add_salaryrecord")


def test_ordinary_employees_get_no_hr_permissions(roles):
    user = user_with_role("employee")
    assert not user.has_perm("hr.view_employee")


# --- Admin ---------------------------------------------------------------------------


@pytest.fixture
def superuser():
    return User.objects.create_superuser("root", "root@example.com", PASSWORD)


def test_admin_lists_employees(client, superuser):
    make_employee()
    client.force_login(superuser)
    response = client.get(reverse("admin:hr_employee_changelist"))
    assert response.status_code == 200
    assert "Abebe Kebede" in response.content.decode()


def test_admin_adds_an_employee_with_a_starting_salary(client, superuser):
    client.force_login(superuser)
    response = client.post(
        reverse("admin:hr_employee_add"),
        {
            "employee_number": "E100",
            "full_name": "Hanna Tesfaye",
            "gender": "female",
            "employment_date": "2026-01-05",
            "employment_type": "permanent",
            "status": "active",
            "salary_records-TOTAL_FORMS": "1",
            "salary_records-INITIAL_FORMS": "0",
            "salary_records-MIN_NUM_FORMS": "0",
            "salary_records-MAX_NUM_FORMS": "1000",
            "salary_records-0-effective_date": "2026-01-05",
            "salary_records-0-basic_salary": "8500.00",
            "salary_records-0-transport_allowance": "0",
            "salary_records-0-other_allowances": "0",
            "salary_records-0-other_allowances_taxable": "on",
            "salary_records-0-reason": "Starting salary",
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    employee = Employee.objects.get(employee_number="E100")
    assert employee.salary_on(date(2026, 2, 1)).basic_salary == Decimal("8500.00")
    assert AuditEvent.objects.filter(action="create", object_type="hr.SalaryRecord").exists()


def test_admin_rejects_a_leaver_without_a_date(client, superuser):
    client.force_login(superuser)
    response = client.post(
        reverse("admin:hr_employee_add"),
        {
            "employee_number": "E101",
            "full_name": "Left Early",
            "employment_date": "2026-01-05",
            "employment_type": "permanent",
            "status": "resigned",
            "salary_records-TOTAL_FORMS": "0",
            "salary_records-INITIAL_FORMS": "0",
            "salary_records-MIN_NUM_FORMS": "0",
            "salary_records-MAX_NUM_FORMS": "1000",
        },
    )
    assert response.status_code == 200
    assert not Employee.objects.filter(employee_number="E101").exists()


def test_position_exists_for_assignment():
    position = Position.objects.create(title="Accountant")
    employee = make_employee(position=position)
    assert employee.position.title == "Accountant"
