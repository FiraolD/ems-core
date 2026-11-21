"""Accounts behaviour that needs Django: sign-in, lockout, forced password change, roles."""
import io
from datetime import timedelta

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.contrib.auth.models import Group  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"
NEW_PASSWORD = "Another-Strong-Pass-42"

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user("abebe", password=PASSWORD)


def sign_in(client, password=PASSWORD, username="abebe"):
    return client.post(reverse("accounts:login"), {"username": username, "password": password})


def signed_in(client):
    return "_auth_user_id" in client.session


# --- Model ---------------------------------------------------------------------------


def test_setting_a_password_records_when(user):
    assert user.password_changed_at is not None


def test_is_locked_follows_locked_until(user):
    assert user.is_locked is False
    user.locked_until = timezone.now() + timedelta(minutes=5)
    assert user.is_locked is True
    user.locked_until = timezone.now() - timedelta(minutes=5)
    assert user.is_locked is False


# --- Sign-in and lockout -------------------------------------------------------------


def test_correct_password_signs_in(client, user):
    response = sign_in(client)
    assert response.status_code == 302
    assert signed_in(client)
    assert client.get("/").status_code == 200


def test_wrong_password_is_refused_and_counted(client, user):
    response = sign_in(client, "wrong-password")
    assert response.status_code == 200
    assert not signed_in(client)
    user.refresh_from_db()
    assert user.failed_login_count == 1


def test_unknown_user_is_refused_without_error(client):
    response = sign_in(client, username="nobody")
    assert response.status_code == 200
    assert not signed_in(client)


def test_account_locks_after_repeated_failures(client, user):
    for _ in range(5):
        sign_in(client, "wrong-password")
    user.refresh_from_db()
    assert user.is_locked
    assert AuditEvent.objects.filter(action="account_locked", object_id=str(user.pk)).exists()

    sign_in(client)  # the correct password is refused while locked
    assert not signed_in(client)


def test_lock_ends_and_success_clears_the_counters(client, user):
    User.objects.filter(pk=user.pk).update(
        failed_login_count=3, locked_until=timezone.now() - timedelta(minutes=1)
    )
    assert sign_in(client).status_code == 302
    user.refresh_from_db()
    assert user.failed_login_count == 0
    assert user.locked_until is None


def test_lockout_can_be_turned_off(client, user, settings):
    settings.EMS_LOCKOUT_MAX_ATTEMPTS = 0
    for _ in range(8):
        sign_in(client, "wrong-password")
    user.refresh_from_db()
    assert not user.is_locked
    assert sign_in(client).status_code == 302


def test_sign_ins_are_audited(client, user):
    sign_in(client, "wrong-password")
    sign_in(client)
    assert AuditEvent.objects.filter(action="login_failed", object_repr="abebe").exists()
    login = AuditEvent.objects.get(action="login")
    assert login.actor_username == "abebe"
    assert login.ip_address == "127.0.0.1"


# --- Forced password change ----------------------------------------------------------


def test_flagged_user_is_sent_to_change_their_password(client):
    flagged = User.objects.create_user("flagged", password=PASSWORD, must_change_password=True)
    client.force_login(flagged)
    response = client.get("/")
    assert response.status_code == 302
    assert response.url == reverse("accounts:password_change")
    assert client.get(reverse("accounts:password_change")).status_code == 200


def test_changing_the_password_clears_the_flag(client):
    flagged = User.objects.create_user("flagged", password=PASSWORD, must_change_password=True)
    client.force_login(flagged)
    response = client.post(
        reverse("accounts:password_change"),
        {"old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
    )
    assert response.status_code == 302
    flagged.refresh_from_db()
    assert flagged.must_change_password is False
    assert flagged.check_password(NEW_PASSWORD)
    assert client.get("/").status_code == 200  # no longer redirected, and still signed in


def test_a_weak_new_password_is_rejected_and_the_flag_stays(client):
    flagged = User.objects.create_user("flagged", password=PASSWORD, must_change_password=True)
    client.force_login(flagged)
    response = client.post(
        reverse("accounts:password_change"),
        {"old_password": PASSWORD, "new_password1": "short", "new_password2": "short"},
    )
    assert response.status_code == 200
    flagged.refresh_from_db()
    assert flagged.must_change_password is True
    assert flagged.check_password(PASSWORD)


def test_a_flagged_user_can_still_sign_out(client):
    flagged = User.objects.create_user("flagged", password=PASSWORD, must_change_password=True)
    client.force_login(flagged)
    assert client.post(reverse("accounts:logout")).status_code == 302
    assert not signed_in(client)


def test_old_passwords_are_forced_to_change_when_expiry_is_on(client, user, settings):
    settings.EMS_PASSWORD_MAX_AGE_DAYS = 30
    User.objects.filter(pk=user.pk).update(password_changed_at=timezone.now() - timedelta(days=40))
    client.force_login(user)
    assert client.get("/").status_code == 302


def test_a_password_set_by_the_user_is_never_flagged_on_its_own(client, user):
    client.force_login(user)
    assert client.get("/").status_code == 200


def test_home_needs_sign_in(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


# --- Roles ---------------------------------------------------------------------------


def test_sync_roles_creates_the_role_groups():
    call_command("sync_roles", "--strict", stdout=io.StringIO())
    admin_group = Group.objects.get(name="admin")
    codenames = set(admin_group.permissions.values_list("codename", flat=True))
    assert {"manage_users", "view_auditevent", "change_company"} <= codenames
    assert Group.objects.filter(name="employee").exists()


def test_sync_roles_is_repeatable():
    call_command("sync_roles", stdout=io.StringIO())
    output = io.StringIO()
    call_command("sync_roles", stdout=output)
    assert "up to date" in output.getvalue()


def test_a_role_grants_its_permissions(user):
    call_command("sync_roles", stdout=io.StringIO())
    user.groups.add(Group.objects.get(name="admin"))
    refreshed = User.objects.get(pk=user.pk)
    assert refreshed.has_perm("accounts.manage_users")
    other = User.objects.create_user("other", password=PASSWORD)
    assert not other.has_perm("accounts.manage_users")


def test_role_changes_are_audited(user):
    call_command("sync_roles", stdout=io.StringIO())
    user.groups.add(Group.objects.get(name="admin"))
    event = AuditEvent.objects.get(action="roles_changed", object_id=str(user.pk))
    assert event.changes == {"groups": {"added": ["admin"]}}
