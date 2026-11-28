"""Leave, overtime and attendance screens (needs Django)."""
import io
from datetime import date
from decimal import Decimal as D

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.core.management import call_command  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from modules.attendance.models import AttendanceRecord  # noqa: E402
from modules.hr.models import Employee  # noqa: E402
from modules.leave.models import LeaveRequest, LeaveType  # noqa: E402
from modules.overtime.models import OvertimeCategory, OvertimeEntry  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"

pytestmark = pytest.mark.django_db


def make_user(role, name):
    user = User.objects.create_user(name, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


@pytest.fixture
def world():
    call_command("sync_roles", "--strict", stdout=io.StringIO())
    call_command("seed_overtime_categories", stdout=io.StringIO())
    me, other, hr = make_user("employee", "me"), make_user("employee", "other"), make_user("hr_manager", "hr")
    mine = Employee.objects.create(employee_number="E1", full_name="Mine", employment_date=date(2020, 1, 1), user=me)
    theirs = Employee.objects.create(employee_number="E2", full_name="Theirs", employment_date=date(2020, 1, 1), user=other)
    annual = LeaveType.objects.create(name="Annual leave", pay_code="annual_leave", uses_balance=True, annual_days=16)
    return dict(me=me, other=other, hr=hr, mine=mine, theirs=theirs, annual=annual)


# --- Pages need sign-in and the right permission ----------------------------------------

@pytest.mark.parametrize("url", ["/leave/", "/overtime/", "/leave/approvals/", "/overtime/approvals/",
                                 "/attendance/import/", "/attendance/report/"])
def test_screens_need_sign_in(client, world, url):
    response = client.get(url)
    assert response.status_code == 302 and "login" in response.url


@pytest.mark.parametrize("url", ["/leave/approvals/", "/overtime/approvals/", "/attendance/import/",
                                 "/attendance/report/"])
def test_staff_screens_are_forbidden_to_ordinary_employees(client, world, url):
    client.force_login(world["me"])
    assert client.get(url).status_code == 403


def test_employees_can_open_their_own_pages(client, world):
    client.force_login(world["me"])
    assert client.get("/leave/").status_code == 200
    assert client.get("/overtime/").status_code == 200


# --- Leave ---------------------------------------------------------------------------------

def test_employee_requests_leave_and_hr_approves_it(client, world):
    client.force_login(world["me"])
    response = client.post("/leave/request/", {"leave_type": world["annual"].pk, "start_date": "2026-09-07",
                                               "end_date": "2026-09-11", "reason": "trip"})
    assert response.status_code == 302
    req = LeaveRequest.objects.get()
    assert req.status == "pending" and req.days == D("5")
    assert "Annual leave" in client.get("/leave/").content.decode()

    client.force_login(world["hr"])
    page = client.get("/leave/approvals/").content.decode()
    assert "Mine" in page
    client.post(f"/leave/{req.pk}/decide/", {"action": "approve", "note": "ok"})
    req.refresh_from_db()
    assert req.status == "approved" and req.decided_by == world["hr"]


def test_a_refused_request_shows_a_message_and_creates_nothing(client, world):
    client.force_login(world["me"])
    response = client.post("/leave/request/", {"leave_type": world["annual"].pk, "start_date": "2026-09-11",
                                               "end_date": "2026-09-07"}, follow=True)
    assert "before the start date" in response.content.decode()
    assert LeaveRequest.objects.count() == 0


def test_a_missing_date_is_handled_without_an_error_page(client, world):
    client.force_login(world["me"])
    response = client.post("/leave/request/", {"leave_type": world["annual"].pk}, follow=True)
    assert response.status_code == 200
    assert "first and last day" in response.content.decode()


def test_employees_cannot_decide_or_cancel_other_peoples_leave(client, world):
    req = LeaveRequest.objects.create(employee=world["theirs"], leave_type=world["annual"],
                                      start_date=date(2026, 9, 7), end_date=date(2026, 9, 8), days=D("2"))
    client.force_login(world["me"])
    assert client.post(f"/leave/{req.pk}/decide/", {"action": "approve"}).status_code == 403
    assert client.post(f"/leave/{req.pk}/cancel/").status_code == 404
    req.refresh_from_db()
    assert req.status == "pending"


def test_an_employee_cancels_their_own_pending_request(client, world):
    req = LeaveRequest.objects.create(employee=world["mine"], leave_type=world["annual"],
                                      start_date=date(2026, 9, 7), end_date=date(2026, 9, 8), days=D("2"))
    client.force_login(world["me"])
    client.post(f"/leave/{req.pk}/cancel/")
    req.refresh_from_db()
    assert req.status == "cancelled"


def test_hr_can_request_leave_for_someone_by_employee_number(client, world):
    client.force_login(world["hr"])
    client.post("/leave/request/", {"employee_number": "E2", "leave_type": world["annual"].pk,
                                    "start_date": "2026-09-07", "end_date": "2026-09-08"})
    assert LeaveRequest.objects.get().employee == world["theirs"]


def test_actions_need_post(client, world):
    client.force_login(world["hr"])
    assert client.get("/leave/request/").status_code == 405
    assert client.get("/overtime/record/").status_code == 405


# --- Overtime ------------------------------------------------------------------------------

def test_employee_records_overtime_and_hr_approves(client, world):
    client.force_login(world["me"])
    client.post("/overtime/record/", {"work_date": "2026-09-08", "hours": "2", "kind": "normal"})
    entry = OvertimeEntry.objects.get()
    assert entry.status == "pending" and entry.multiplier == D("1.25")
    client.force_login(world["hr"])
    assert "Mine" in client.get("/overtime/approvals/").content.decode()
    client.post(f"/overtime/{entry.pk}/decide/", {"action": "approve"})
    entry.refresh_from_db()
    assert entry.status == "approved"


def test_overtime_rule_errors_are_shown_not_raised(client, world):
    client.force_login(world["me"])
    response = client.post("/overtime/record/", {"work_date": "2026-09-13", "hours": "2", "kind": "normal"},
                           follow=True)  # 13 Sep 2026 is a Sunday: the rest day
    assert "weekly rest day" in response.content.decode()
    assert OvertimeEntry.objects.count() == 0


def test_bad_hours_text_does_not_crash(client, world):
    client.force_login(world["me"])
    response = client.post("/overtime/record/", {"work_date": "2026-09-08", "hours": "lots", "kind": "normal"},
                           follow=True)
    assert response.status_code == 200 and OvertimeEntry.objects.count() == 0


def test_employees_cannot_touch_other_peoples_overtime(client, world):
    entry = OvertimeEntry.objects.create(employee=world["theirs"], work_date=date(2026, 9, 8), hours=D("2"),
                                         category=OvertimeCategory.objects.get(kind="normal"), multiplier=D("1.25"))
    client.force_login(world["me"])
    assert client.post(f"/overtime/{entry.pk}/cancel/").status_code == 404
    assert client.post(f"/overtime/{entry.pk}/decide/", {"action": "approve"}).status_code == 403


# --- Attendance ---------------------------------------------------------------------------

def csv_upload(text, name="a.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


def test_hr_imports_a_file_and_sees_the_summary(client, world):
    client.force_login(world["hr"])
    body = "employee_number,date,status,note\nE1,2026-09-01,absent,\nE1,2026-09-02,late,\n"
    response = client.post("/attendance/import/", {"file": csv_upload(body)}, follow=True)
    assert "2 added" in response.content.decode()
    assert AttendanceRecord.objects.count() == 2


def test_a_bad_file_shows_every_problem_and_imports_nothing(client, world):
    client.force_login(world["hr"])
    body = "employee_number,date,status,note\nZZ,2026-09-01,absent,\nE1,nope,absent,\n"
    response = client.post("/attendance/import/", {"file": csv_upload(body)})
    text = response.content.decode()
    assert "Nothing was imported" in text and "unknown employee" in text and "YYYY-MM-DD" in text
    assert AttendanceRecord.objects.count() == 0


def test_non_utf8_and_missing_files_are_handled(client, world):
    client.force_login(world["hr"])
    bad = SimpleUploadedFile("a.csv", b"\xff\xfe\x00bad", content_type="text/csv")
    assert "UTF-8" in client.post("/attendance/import/", {"file": bad}, follow=True).content.decode()
    assert "Choose a CSV file" in client.post("/attendance/import/", {}, follow=True).content.decode()


def test_monthly_report_and_csv_export(client, world):
    AttendanceRecord.objects.create(employee=world["mine"], date=date(2026, 9, 1), status="absent")
    AttendanceRecord.objects.create(employee=world["mine"], date=date(2026, 9, 2), status="late")
    client.force_login(world["hr"])
    page = client.get("/attendance/report/?year=2026&month=9").content.decode()
    assert "September 2026" in page and "Mine" in page
    response = client.get("/attendance/report/2026/9.csv")
    assert response.status_code == 200 and response["Content-Type"].startswith("text/csv")
    text = response.content.decode("utf-8-sig")
    assert "E1,Mine,0,1,1,0" in text and "TOTAL" in text
    assert AuditEvent.objects.filter(action="attendance.report_exported").exists()


def test_report_ignores_a_nonsense_month(client, world):
    client.force_login(world["hr"])
    assert client.get("/attendance/report/?year=abc&month=99").status_code == 200


def test_workspace_links_follow_permissions(client, world):
    client.force_login(world["hr"])
    page = client.get("/").content.decode()
    assert "/leave/approvals/" in page and "/attendance/import/" in page
    client.force_login(world["me"])
    page = client.get("/").content.decode()
    assert "/leave/" in page and "/leave/approvals/" not in page and "/attendance/import/" not in page
