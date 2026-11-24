"""The audit log: append-only guarantees and the automatic model trail."""
import json

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import DatabaseError, connection, transaction  # noqa: E402

from core.audit.changes import REDACTED  # noqa: E402
from core.audit.context import AuditContext, reset_context, set_context  # noqa: E402
from core.audit.models import AuditEvent, AuditImmutableError  # noqa: E402
from core.audit.service import record  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"

pytestmark = pytest.mark.django_db


# --- Append-only ---------------------------------------------------------------------


def test_an_event_cannot_be_changed():
    event = record("test.action")
    event.action = "something.else"
    with pytest.raises(AuditImmutableError):
        event.save()


def test_events_cannot_be_deleted_one_by_one_or_in_bulk():
    event = record("test.action")
    with pytest.raises(AuditImmutableError):
        event.delete()
    with pytest.raises(AuditImmutableError):
        AuditEvent.objects.all().delete()


def test_events_cannot_be_bulk_updated():
    record("test.action")
    with pytest.raises(AuditImmutableError):
        AuditEvent.objects.update(action="hidden")


@pytest.mark.skipif(connection.vendor != "postgresql", reason="trigger exists on PostgreSQL only")
def test_postgres_refuses_raw_sql_changes():
    event = record("test.action")
    for sql in ("UPDATE audit_auditevent SET action = 'x' WHERE id = %s",
                "DELETE FROM audit_auditevent WHERE id = %s"):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, [event.pk])
    assert AuditEvent.objects.filter(pk=event.pk, action="test.action").exists()


# --- record() ------------------------------------------------------------------------


def test_record_takes_the_actor_from_the_context():
    token = set_context(AuditContext(5, "hr.user", "10.0.0.9", "TestBrowser/1.0"))
    try:
        event = record("test.action", object_type="demo.Thing", object_id="7", object_repr="Thing 7")
    finally:
        reset_context(token)
    assert (event.actor_id, event.actor_username) == (5, "hr.user")
    assert event.ip_address == "10.0.0.9"
    assert event.user_agent == "TestBrowser/1.0"
    assert (event.object_type, event.object_id, event.object_repr) == ("demo.Thing", "7", "Thing 7")


def test_record_outside_a_request_has_no_actor():
    event = record("test.action")
    assert event.actor_id is None and event.actor_username == ""


def test_record_stores_json_safe_changes():
    from decimal import Decimal

    event = record("test.action", changes={"pay": {"old": Decimal("1.10"), "new": Decimal("2.20")}})
    event.refresh_from_db()
    assert event.changes == {"pay": {"old": "1.10", "new": "2.20"}}


# --- Automatic trail for registered models (the user model is registered) -----------


def test_creating_a_user_is_audited_without_the_password():
    user = User.objects.create_user("abebe", password=PASSWORD)
    event = AuditEvent.objects.get(action="create", object_id=str(user.pk))
    assert event.object_type == "accounts.User"
    assert event.changes["username"] == {"old": None, "new": "abebe"}
    assert event.changes["password"] == {"old": REDACTED, "new": REDACTED}
    assert PASSWORD not in json.dumps(event.changes)
    assert user.password not in json.dumps(event.changes)


def test_an_update_records_only_what_changed():
    user = User.objects.create_user("abebe", password=PASSWORD)
    user.first_name = "Abebe"
    user.save()
    event = AuditEvent.objects.get(action="update", object_id=str(user.pk))
    assert event.changes == {"first_name": {"old": "", "new": "Abebe"}}


def test_saving_without_changes_records_nothing():
    user = User.objects.create_user("abebe", password=PASSWORD)
    before = AuditEvent.objects.count()
    user.save()
    assert AuditEvent.objects.count() == before


def test_a_partial_save_only_audits_the_fields_it_saves():
    user = User.objects.create_user("abebe", password=PASSWORD)
    user.first_name = "Abebe"
    user.last_name = "Kebede"
    user.save(update_fields=["first_name"])
    event = AuditEvent.objects.get(action="update", object_id=str(user.pk))
    assert set(event.changes) == {"first_name"}


def test_money_is_logged_at_database_precision_and_equal_amounts_are_no_change():
    from datetime import date
    from decimal import Decimal

    from modules.hr.models import Employee, SalaryRecord

    employee = Employee.objects.create(
        employee_number="E1", full_name="A B", employment_date=date(2024, 1, 1)
    )
    record = SalaryRecord.objects.create(
        employee=employee, effective_date=date(2025, 1, 1), basic_salary=Decimal("10000")
    )
    created = AuditEvent.objects.get(action="create", object_type="hr.SalaryRecord")
    assert created.changes["basic_salary"] == {"old": None, "new": "10000.00"}
    before = AuditEvent.objects.count()
    record.basic_salary = Decimal("10000.0")  # same amount, written differently
    record.save()
    assert AuditEvent.objects.count() == before
    record.basic_salary = Decimal("12000")
    record.save()
    updated = AuditEvent.objects.get(action="update", object_type="hr.SalaryRecord")
    assert updated.changes == {"basic_salary": {"old": "10000.00", "new": "12000.00"}}


def test_noisy_fields_are_excluded():
    user = User.objects.create_user("abebe", password=PASSWORD)
    before = AuditEvent.objects.filter(action="update").count()
    user.failed_login_count = 3
    user.save(update_fields=["failed_login_count"])
    assert AuditEvent.objects.filter(action="update").count() == before


def test_deleting_a_user_is_audited():
    user = User.objects.create_user("abebe", password=PASSWORD)
    pk = str(user.pk)
    user.delete()
    event = AuditEvent.objects.get(action="delete", object_id=pk)
    assert event.changes["username"] == {"old": "abebe", "new": None}
    assert event.changes["password"] == {"old": REDACTED, "new": REDACTED}
