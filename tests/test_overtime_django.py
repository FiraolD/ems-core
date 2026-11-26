"""Overtime workflow, rate snapshot, roles (needs Django)."""
import io
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.exceptions import PermissionDenied  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.utils import timezone  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from modules.hr.models import Employee  # noqa: E402
from modules.overtime import service  # noqa: E402
from modules.overtime.models import OvertimeCategory, OvertimeEntry  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"

pytestmark = pytest.mark.django_db

MON = date(2026, 9, 7)      # an ordinary Monday
SUNDAY = date(2026, 9, 13)  # the default weekly rest day


@pytest.fixture
def roles():
    call_command("sync_roles", "--strict", stdout=io.StringIO())


def make_user(role, name):
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def world(roles):
    call_command("seed_overtime_categories", stdout=io.StringIO())
    me = make_user("employee", "me")
    hr = make_user("hr_manager", "hr")
    emp = Employee.objects.create(employee_number="E1", full_name="P", employment_date=date(2020, 1, 1), user=me)
    return dict(me=me, hr=hr, emp=emp)


def test_seed_is_repeatable_and_keeps_edits():
    call_command("seed_overtime_categories", stdout=io.StringIO())
    OvertimeCategory.objects.filter(kind="night").update(multiplier=D("1.75"))
    call_command("seed_overtime_categories", stdout=io.StringIO())
    assert OvertimeCategory.objects.count() == 4
    assert OvertimeCategory.objects.get(kind="night").multiplier == D("1.75")


def test_employee_records_own_overtime_with_the_rate_copied_in(world):
    entry = service.record_overtime(world["emp"], MON, "2", "normal", world["me"], reason="deadline")
    assert entry.status == "pending" and entry.multiplier == D("1.25")
    OvertimeCategory.objects.filter(kind="normal").update(multiplier=D("1.50"))
    entry.refresh_from_db()
    assert entry.multiplier == D("1.25")  # later rate changes do not rewrite history
    assert AuditEvent.objects.filter(action="overtime.requested").exists()


def test_day_and_category_must_agree(world):
    with pytest.raises(service.OvertimeRefused, match="weekly rest day"):
        service.record_overtime(world["emp"], SUNDAY, "2", "normal", world["me"])
    assert service.record_overtime(world["emp"], SUNDAY, "2", "rest_day", world["me"]).multiplier == D("2.00")


def test_a_public_holiday_must_use_the_holiday_rate(world):
    from modules.attendance.models import PublicHoliday

    PublicHoliday.objects.create(date=date(2026, 9, 9), name="Holiday")
    with pytest.raises(service.OvertimeRefused, match="public holiday"):
        service.record_overtime(world["emp"], date(2026, 9, 9), "2", "normal", world["me"])
    assert service.record_overtime(world["emp"], date(2026, 9, 9), "2", "public_holiday", world["me"])


def test_future_dates_pre_start_and_leavers_are_refused(world):
    with pytest.raises(service.OvertimeRefused, match="future"):
        service.record_overtime(world["emp"], timezone.localdate() + timedelta(days=3), "1", "normal", world["me"])
    with pytest.raises(service.OvertimeRefused, match="start date"):
        service.record_overtime(world["emp"], date(2019, 12, 2), "1", "normal", world["me"])
    Employee.objects.filter(pk=world["emp"].pk).update(status="resigned")
    with pytest.raises(service.OvertimeRefused, match="left"):
        service.record_overtime(Employee.objects.get(pk=world["emp"].pk), MON, "1", "normal", world["me"])


def test_an_inactive_or_missing_rate_blocks_recording(world):
    OvertimeCategory.objects.filter(kind="night").update(is_active=False)
    with pytest.raises(service.OvertimeRefused, match="no active rate"):
        service.record_overtime(world["emp"], MON, "1", "night", world["me"])


def test_nobody_records_for_others_without_permission(world, roles):
    other = make_user("employee", "other")
    with pytest.raises(PermissionDenied):
        service.record_overtime(world["emp"], MON, "1", "normal", other)
    assert service.record_overtime(world["emp"], MON, "1", "normal", world["hr"]).requested_by == world["hr"]


def test_approval_rules(world):
    entry = service.record_overtime(world["emp"], MON, "2", "normal", world["me"])
    with pytest.raises(PermissionDenied):
        service.decide(entry, world["me"], approve=True)
    service.decide(entry, world["hr"], approve=True)
    entry.refresh_from_db()
    assert entry.status == "approved" and entry.decided_by == world["hr"]
    with pytest.raises(service.OvertimeRefused, match="already approved"):
        service.decide(entry, world["hr"], approve=False)


def test_you_cannot_approve_your_own_overtime(world):
    world["me"].groups.add(Group.objects.get(name="hr_manager"))
    both = User.objects.get(pk=world["me"].pk)
    entry = service.record_overtime(world["emp"], MON, "2", "normal", both)
    with pytest.raises(service.OvertimeRefused, match="your own"):
        service.decide(entry, both, approve=True)


def test_only_approved_entries_reach_payroll(world):
    ok = service.record_overtime(world["emp"], MON, "2", "normal", world["me"])
    service.record_overtime(world["emp"], MON + timedelta(days=1), "3", "normal", world["me"])  # stays pending
    service.decide(ok, world["hr"], approve=True)
    got = service.approved_entries(world["emp"], date(2026, 9, 1), date(2026, 9, 30))
    assert got == [(D("2.00"), D("1.25"))]
    assert service.approved_entries(world["emp"], date(2026, 10, 1), date(2026, 10, 31)) == []


def test_cancelling_rules(world):
    entry = service.record_overtime(world["emp"], MON, "2", "normal", world["me"])
    service.cancel(entry, world["me"])
    assert OvertimeEntry.objects.get(pk=entry.pk).status == "cancelled"
    approved = service.record_overtime(world["emp"], MON, "2", "normal", world["me"])
    service.decide(approved, world["hr"], approve=True)
    with pytest.raises(PermissionDenied):
        service.cancel(approved, world["me"])
    service.cancel(approved, world["hr"])
    assert service.approved_entries(world["emp"], MON, MON) == []


def test_role_grants(roles):
    assert make_user("hr_manager", "hr").has_perm("overtime.approve_overtimeentry")
    assert not make_user("hr_manager", "hr2").has_perm("overtime.delete_overtimeentry")
    assert not make_user("employee", "e").has_perm("overtime.approve_overtimeentry")
    assert make_user("payroll_officer", "p").has_perm("overtime.view_overtimeentry")
