"""The company record and the admin screens built on the accounts, audit and company apps."""
import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import IntegrityError, transaction  # noqa: E402
from django.urls import reverse  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from core.company.models import Company, CompanyDeletionError  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"
NEW_PASSWORD = "Another-Strong-Pass-42"

pytestmark = pytest.mark.django_db


@pytest.fixture
def superuser():
    return User.objects.create_superuser("root", "root@example.com", PASSWORD)


# --- Company -------------------------------------------------------------------------


def test_company_is_created_from_the_client_config():
    company = Company.get()
    assert company.pk == 1
    assert company.legal_name == "Example Company PLC"
    assert company.currency_code == "ETB"
    assert Company.get().pk == company.pk
    assert Company.objects.count() == 1


def test_creating_the_company_is_audited():
    Company.get()
    event = AuditEvent.objects.get(action="create", object_type="company.Company")
    assert event.changes["legal_name"]["new"] == "Example Company PLC"


def test_saving_always_uses_row_one():
    Company.get()
    Company(legal_name="Renamed PLC").save()
    assert Company.objects.count() == 1
    assert Company.objects.get().legal_name == "Renamed PLC"


def test_a_second_company_is_impossible():
    Company.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        Company.objects.bulk_create([Company(id=2, legal_name="Other PLC")])


def test_the_company_cannot_be_deleted():
    with pytest.raises(CompanyDeletionError):
        Company.get().delete()


def test_home_page_shows_the_company_name(client):
    user = User.objects.create_user("abebe", password=PASSWORD)
    client.force_login(user)
    assert "Example Company PLC" in client.get("/").content.decode()


# --- Admin ---------------------------------------------------------------------------


def test_company_list_jumps_to_the_single_record(client, superuser):
    client.force_login(superuser)
    response = client.get("/admin/company/company/")
    assert response.status_code == 302
    assert response.url == reverse("admin:company_company_change", args=[1])


def test_editing_the_company_in_admin_is_audited_with_actor_and_address(client, superuser):
    client.force_login(superuser)
    Company.get()
    response = client.post(
        reverse("admin:company_company_change", args=[1]),
        {
            "legal_name": "Example Company PLC",
            "trade_name": "",
            "tin": "",
            "address": "",
            "city": "Adama",
            "phone": "",
            "email": "",
            "currency_code": "ETB",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    event = AuditEvent.objects.get(action="update", object_type="company.Company")
    assert event.changes == {"city": {"old": "", "new": "Adama"}}
    assert event.actor_username == "root"
    assert event.ip_address == "127.0.0.1"


def test_users_created_in_admin_must_change_their_password(client, superuser):
    client.force_login(superuser)
    response = client.post(
        reverse("admin:accounts_user_add"),
        {
            "username": "newhire",
            "password1": NEW_PASSWORD,
            "password2": NEW_PASSWORD,
            "usable_password": "true",
        },
    )
    assert response.status_code == 302
    assert User.objects.get(username="newhire").must_change_password is True


def test_admin_password_reset_forces_a_change(client, superuser):
    target = User.objects.create_user("abebe", password=PASSWORD)
    client.force_login(superuser)
    response = client.post(
        reverse("admin:auth_user_password_change", args=[target.pk]),
        {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD, "usable_password": "true"},
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.must_change_password is True
    assert target.check_password(NEW_PASSWORD)


def test_admin_can_unlock_accounts(client, superuser):
    from datetime import timedelta

    from django.utils import timezone

    target = User.objects.create_user("abebe", password=PASSWORD)
    User.objects.filter(pk=target.pk).update(
        failed_login_count=2, locked_until=timezone.now() + timedelta(minutes=10)
    )
    client.force_login(superuser)
    response = client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "unlock_accounts", "_selected_action": [target.pk]},
    )
    assert response.status_code == 302
    target.refresh_from_db()
    assert target.locked_until is None and target.failed_login_count == 0
    assert AuditEvent.objects.filter(action="account_unlocked", object_id=str(target.pk)).exists()


def test_the_audit_log_is_read_only_in_admin(client, superuser):
    client.force_login(superuser)
    assert client.get("/admin/audit/auditevent/").status_code == 200
    assert client.get("/admin/audit/auditevent/add/").status_code == 403
