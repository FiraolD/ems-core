"""Attendance models, import service, roles (needs Django)."""
import io
from datetime import date

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.exceptions import PermissionDenied, ValidationError  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.db import IntegrityError, transaction  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from modules.attendance import service  # noqa: E402
from modules.attendance.models import AttendanceRecord  # noqa: E402
from modules.hr.models import Employee  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"
HEADER = "employee_number,date,status,note\n"

pytestmark = pytest.mark.django_db


@pytest.fixture
def roles():
    call_command("sync_roles", "--strict", stdout=io.StringIO())


def user_with_role(role):
    user = User.objects.create_user(role, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def hr(roles):
    return user_with_role("hr_manager")


@pytest.fixture
def emp():
    return Employee.objects.create(employee_number="E1", full_name="Person", employment_date=date(2026, 1, 1))


def test_one_record_per_employee_per_day(emp):
    AttendanceRecord.objects.create(employee=emp, date=date(2026, 9, 1), status="absent")
    with pytest.raises(IntegrityError), transaction.atomic():
        AttendanceRecord.objects.create(employee=emp, date=date(2026, 9, 1), status="present")


def test_a_record_before_the_start_date_is_invalid(emp):
    record = AttendanceRecord(employee=emp, date=date(2025, 12, 31), status="absent")
    with pytest.raises(ValidationError):
        record.full_clean()


def test_import_creates_updates_and_reports_unchanged(emp, hr):
    first = service.import_csv(HEADER + "E1,2026-09-01,absent,\nE1,2026-09-02,late,\n", hr)
    assert (first.created, first.updated, first.unchanged) == (2, 0, 0)
    second = service.import_csv(HEADER + "E1,2026-09-01,half_day,\nE1,2026-09-02,late,\n", hr)
    assert (second.created, second.updated, second.unchanged) == (0, 1, 1)
    row = AttendanceRecord.objects.get(employee=emp, date=date(2026, 9, 1))
    assert row.status == "half_day" and row.source == "import" and row.recorded_by == hr
    assert AuditEvent.objects.filter(action="attendance.imported").count() == 2


def test_a_bad_file_imports_nothing(emp, hr):
    with pytest.raises(service.ImportRejected) as caught:
        service.import_csv(HEADER + "E1,2026-09-01,absent,\nE1,2026-09-02,bogus,\n", hr)
    assert caught.value.errors
    assert AttendanceRecord.objects.count() == 0


def test_import_rejects_days_before_the_employee_started(emp, hr):
    with pytest.raises(service.ImportRejected):
        service.import_csv(HEADER + "E1,2025-12-01,absent,\n", hr)
    assert AttendanceRecord.objects.count() == 0


def test_only_hr_may_import(emp, roles):
    with pytest.raises(PermissionDenied):
        service.import_csv(HEADER + "E1,2026-09-01,absent,\n", user_with_role("payroll_officer"))
    with pytest.raises(PermissionDenied):
        service.import_csv(HEADER + "E1,2026-09-01,absent,\n", None)


def test_role_grants_for_attendance(roles):
    hr_user = user_with_role("hr_manager")
    assert hr_user.has_perm("attendance.change_attendancerecord")
    assert not hr_user.has_perm("attendance.delete_attendancerecord")
    assert user_with_role("payroll_officer").has_perm("attendance.view_attendancerecord")
    assert not user_with_role("payroll_officer").has_perm("attendance.add_attendancerecord")
