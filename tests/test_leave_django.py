"""Leave workflow: requests, approval rules, balances, roles (needs Django)."""
import io
from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.exceptions import PermissionDenied  # noqa: E402
from django.core.management import call_command  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from modules.hr.models import Employee  # noqa: E402
from modules.leave import service  # noqa: E402
from modules.leave.models import LeaveAdjustment, LeaveType  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"

pytestmark = pytest.mark.django_db


@pytest.fixture
def roles():
    call_command("sync_roles", "--strict", stdout=io.StringIO())


def make_user(role, name):
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def world(roles):
    me = make_user("employee", "me")
    hr = make_user("hr_manager", "hr")
    emp = Employee.objects.create(
        employee_number="E1", full_name="Person", employment_date=date(2020, 1, 1), user=me
    )
    annual = LeaveType.objects.create(
        name="Annual leave", pay_code="annual_leave", uses_balance=True, annual_days=16, extra_day_every_years=0
    )
    sick = LeaveType.objects.create(name="Sick leave", pay_code="sick_leave")
    return dict(me=me, hr=hr, emp=emp, annual=annual, sick=sick)


# 2026-09-07 is a Monday; Sunday is the default weekly rest day.
MON, FRI = date(2026, 9, 7), date(2026, 9, 11)


def test_an_employee_can_request_their_own_leave(world):
    req = service.request_leave(world["emp"], world["annual"], MON, FRI, world["me"], reason="trip")
    assert req.status == "pending" and req.days == D("5")
    assert AuditEvent.objects.filter(action="leave.requested").exists()


def test_nobody_requests_for_someone_else_without_permission(world, roles):
    other = make_user("employee", "other")
    with pytest.raises(PermissionDenied):
        service.request_leave(world["emp"], world["annual"], MON, FRI, other)
    assert service.request_leave(world["emp"], world["annual"], MON, FRI, world["hr"]).requested_by == world["hr"]


def test_hr_approves_and_the_balance_drops(world):
    req = service.request_leave(world["emp"], world["annual"], MON, FRI, world["me"])
    service.decide(req, world["hr"], approve=True, note="enjoy")
    req.refresh_from_db()
    assert req.status == "approved" and req.decided_by == world["hr"]
    assert service.balance(world["emp"], world["annual"], 2026).remaining == D("11")
    assert AuditEvent.objects.filter(action="leave.approved").exists()


def test_you_cannot_decide_your_own_request(world):
    me_hr = world["me"]
    me_hr.groups.add(Group.objects.get(name="hr_manager"))
    me_hr = User.objects.get(pk=me_hr.pk)
    req = service.request_leave(world["emp"], world["annual"], MON, FRI, me_hr)
    with pytest.raises(service.LeaveRefused, match="your own"):
        service.decide(req, me_hr, approve=True)


def test_only_approvers_can_decide(world):
    req = service.request_leave(world["emp"], world["annual"], MON, FRI, world["me"])
    with pytest.raises(PermissionDenied):
        service.decide(req, world["me"], approve=True)


def test_a_request_is_decided_once(world):
    req = service.request_leave(world["emp"], world["annual"], MON, FRI, world["me"])
    service.decide(req, world["hr"], approve=False)
    with pytest.raises(service.LeaveRefused, match="already rejected"):
        service.decide(req, world["hr"], approve=True)


def test_overlapping_requests_are_refused(world):
    service.request_leave(world["emp"], world["annual"], MON, FRI, world["me"])
    with pytest.raises(service.LeaveRefused, match="overlaps"):
        service.request_leave(world["emp"], world["sick"], FRI, date(2026, 9, 12), world["me"])


def test_cannot_ask_for_more_than_the_balance_including_pending(world):
    service.request_leave(world["emp"], world["annual"], date(2026, 9, 1), date(2026, 9, 15), world["me"])  # 13 days
    with pytest.raises(service.LeaveRefused, match="Not enough"):
        service.request_leave(world["emp"], world["annual"], date(2026, 10, 5), date(2026, 10, 9), world["me"])


def test_types_without_a_balance_are_not_limited(world):
    req = service.request_leave(world["emp"], world["sick"], date(2026, 9, 1), date(2026, 9, 30), world["me"])
    assert req.days > 16


def test_adjustments_change_the_balance(world):
    LeaveAdjustment.objects.create(employee=world["emp"], leave_type=world["annual"], year=2026, days=D("4"), reason="opening")
    assert service.balance(world["emp"], world["annual"], 2026).remaining == D("20")


def test_public_holidays_are_not_counted(world):
    from modules.attendance.models import PublicHoliday

    PublicHoliday.objects.create(date=date(2026, 9, 9), name="Test holiday")
    req = service.request_leave(world["emp"], world["annual"], MON, FRI, world["me"])
    assert req.days == D("4")


def test_cancelling_rules(world):
    req = service.request_leave(world["emp"], world["annual"], MON, FRI, world["me"])
    service.cancel(req, world["me"])
    req.refresh_from_db()
    assert req.status == "cancelled"
    approved = service.request_leave(world["emp"], world["annual"], MON, FRI, world["me"])
    service.decide(approved, world["hr"], approve=True)
    with pytest.raises(PermissionDenied):
        service.cancel(approved, world["me"])  # an employee cannot undo approved leave
    service.cancel(approved, world["hr"])
    assert service.balance(world["emp"], world["annual"], 2026).remaining == D("16")


def test_a_leaver_or_pre_start_request_is_refused(world):
    with pytest.raises(service.LeaveRefused, match="start date"):
        service.request_leave(world["emp"], world["annual"], date(2019, 12, 2), date(2019, 12, 3), world["me"])
    Employee.objects.filter(pk=world["emp"].pk).update(status="resigned")
    emp = Employee.objects.get(pk=world["emp"].pk)
    with pytest.raises(service.LeaveRefused, match="left"):
        service.request_leave(emp, world["annual"], MON, FRI, world["me"])


def test_seed_command_is_repeatable_and_keeps_edits():
    call_command("seed_leave_types", stdout=io.StringIO())
    LeaveType.objects.filter(name="Annual leave").update(annual_days=20)
    call_command("seed_leave_types", stdout=io.StringIO())
    assert LeaveType.objects.get(name="Annual leave").annual_days == 20
    assert LeaveType.objects.count() == 6


def test_role_grants(roles):
    hr = make_user("hr_manager", "hr")
    assert hr.has_perm("leave.approve_leaverequest")
    assert not hr.has_perm("leave.delete_leaverequest")
    assert not make_user("employee", "e").has_perm("leave.approve_leaverequest")
    assert make_user("payroll_officer", "p").has_perm("leave.view_leaverequest")
