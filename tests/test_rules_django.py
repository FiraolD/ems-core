"""Rules entered in the system: validation, precedence, effective dates, admin, roles."""
import dataclasses
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
from django.core.management import CommandError, call_command  # noqa: E402
from django.db import IntegrityError, transaction  # noqa: E402
from django.urls import reverse  # noqa: E402

from core.audit.models import AuditEvent  # noqa: E402
from core.rules.models import RuleValue, TaxBand, TaxSchedule  # noqa: E402
from core.rules.service import pay_rules_for, rules_for, tax_brackets_for  # noqa: E402
from countries.et import default_brackets  # noqa: E402
from countries.et.tax import BracketError, calculate_paye  # noqa: E402

User = get_user_model()
PASSWORD = "Correct-Horse-9-Battery"

pytestmark = pytest.mark.django_db


def add_rule(key, value, y, m, d, **extra):
    return RuleValue.objects.create(key=key, value=value, effective_from=date(y, m, d), **extra)


def add_schedule(effective, bands, note=""):
    schedule = TaxSchedule.objects.create(effective_from=effective, note=note)
    for low, high, rate, quick in bands:
        TaxBand.objects.create(
            schedule=schedule,
            min_income=Decimal(low),
            max_income=None if high is None else Decimal(high),
            rate=Decimal(rate),
            quick_deduction=Decimal(quick),
        )
    return schedule


# --- Rule values ---------------------------------------------------------------------


def test_values_are_checked_and_tidied_on_save():
    rule = add_rule("transport_taxable", " NO ", 2026, 7, 1)
    rule.refresh_from_db()
    assert rule.value == "no" and rule.typed_value is False


def test_bad_values_are_refused():
    for key, value in [
        ("transport_taxable", "maybe"),
        ("absence_divisor", "99"),
        ("pension_employee_rate", "7"),
    ]:
        with pytest.raises(ValidationError):
            add_rule(key, value, 2026, 7, 1)
    assert RuleValue.objects.count() == 0


def test_unknown_rules_are_refused():
    with pytest.raises(ValidationError):
        add_rule("made_up_rule", "1", 2026, 7, 1)


def test_one_value_per_rule_per_date():
    add_rule("absence_divisor", "30", 2026, 1, 1)
    with pytest.raises(IntegrityError), transaction.atomic():
        RuleValue.objects.bulk_create(
            [RuleValue(key="absence_divisor", value="26", effective_from=date(2026, 1, 1))]
        )


# --- Which rules apply when ----------------------------------------------------------


def test_with_nothing_entered_the_country_defaults_apply():
    rules = pay_rules_for(date(2026, 9, 30))
    assert rules.transport_taxable is True
    assert rules.pension_employee_rate == Decimal("0.07")


def test_client_toml_overrides_the_default(settings):
    settings.EMS_CLIENT = dataclasses.replace(
        settings.EMS_CLIENT, rule_overrides={"transport_taxable": False}
    )
    assert pay_rules_for(date(2026, 9, 30)).transport_taxable is False


def test_a_value_set_in_the_system_beats_client_toml(settings):
    settings.EMS_CLIENT = dataclasses.replace(
        settings.EMS_CLIENT, rule_overrides={"transport_taxable": False}
    )
    add_rule("transport_taxable", "yes", 2026, 1, 1)
    assert pay_rules_for(date(2026, 9, 30)).transport_taxable is True


def test_a_change_applies_only_from_its_start_date():
    add_rule("transport_taxable", "no", 2026, 7, 1, note="Directive 123")
    assert pay_rules_for(date(2026, 6, 30)).transport_taxable is True
    assert pay_rules_for(date(2026, 7, 1)).transport_taxable is False
    assert pay_rules_for(date(2026, 12, 31)).transport_taxable is False


def test_a_later_change_replaces_an_earlier_one_only_after_it_starts():
    add_rule("pension_employee_rate", "0.07", 2025, 1, 1)
    add_rule("pension_employee_rate", "0.08", 2027, 1, 1)
    assert pay_rules_for(date(2026, 6, 30)).pension_employee_rate == Decimal("0.07")
    assert pay_rules_for(date(2027, 1, 31)).pension_employee_rate == Decimal("0.08")


# --- Tax schedules -------------------------------------------------------------------


def test_default_schedule_applies_when_none_is_entered():
    assert tax_brackets_for(date(2026, 9, 30)) == tuple(default_brackets())


def test_a_schedule_applies_from_its_start_date():
    add_schedule(
        date(2026, 7, 1),
        [("0", "5000", "0", "0"), ("5000.01", None, "0.10", "500")],
        note="New directive",
    )
    before = tax_brackets_for(date(2026, 6, 30))
    after = tax_brackets_for(date(2026, 7, 1))
    assert before == tuple(default_brackets())
    assert len(after) == 2
    assert calculate_paye(10000, after).paye == Decimal("500.00")  # 10000 x 10% - 500
    assert calculate_paye(10000, before).paye == Decimal("1650.00")


def test_a_broken_schedule_stops_payroll_instead_of_miscalculating():
    add_schedule(date(2026, 7, 1), [("0", "2000", "0", "0"), ("3000", None, "0.15", "300")])
    with pytest.raises(BracketError):
        tax_brackets_for(date(2026, 8, 1))


def test_an_empty_schedule_is_an_error_not_free_tax():
    TaxSchedule.objects.create(effective_from=date(2026, 7, 1))
    with pytest.raises(BracketError):
        tax_brackets_for(date(2026, 8, 1))


def test_rules_for_bundles_rules_brackets_and_a_snapshot():
    add_rule("transport_taxable", "no", 2026, 7, 1)
    found = rules_for(date(2026, 9, 30))
    assert found.rules.transport_taxable is False
    assert found.snapshot["transport_taxable"] is False
    assert found.snapshot["tax_brackets"][0]["min_income"] == "0"
    assert len(found.snapshot["tax_brackets"]) == len(found.brackets)


def test_seed_command_creates_the_default_schedule():
    out = io.StringIO()
    call_command("seed_tax_schedule", "--effective-from", "2025-07-01", stdout=out)
    schedule = TaxSchedule.objects.get(effective_from=date(2025, 7, 1))
    assert schedule.bands.count() == 6
    assert tax_brackets_for(date(2026, 1, 1)) == tuple(default_brackets())


def test_seed_command_refuses_a_date_that_is_taken_or_malformed():
    call_command("seed_tax_schedule", "--effective-from", "2025-07-01", stdout=io.StringIO())
    with pytest.raises(CommandError, match="already starts"):
        call_command("seed_tax_schedule", "--effective-from", "2025-07-01")
    with pytest.raises(CommandError, match="YYYY|2025-07-01"):
        call_command("seed_tax_schedule", "--effective-from", "July 2025")


# --- Audit ---------------------------------------------------------------------------


def test_rule_changes_are_audited():
    rule = add_rule("transport_taxable", "no", 2026, 7, 1, note="Directive 123")
    event = AuditEvent.objects.get(action="create", object_type="rules.RuleValue")
    assert event.changes["value"] == {"old": None, "new": "no"}
    assert event.object_id == str(rule.pk)


# --- Admin ---------------------------------------------------------------------------


@pytest.fixture
def superuser():
    return User.objects.create_superuser("root", "root@example.com", PASSWORD)


def schedule_post(bands, effective="2026-07-01"):
    data = {
        "effective_from": effective,
        "note": "Test",
        "bands-TOTAL_FORMS": str(len(bands)),
        "bands-INITIAL_FORMS": "0",
        "bands-MIN_NUM_FORMS": "1",
        "bands-MAX_NUM_FORMS": "1000",
    }
    for i, (low, high, rate, quick) in enumerate(bands):
        data[f"bands-{i}-min_income"] = low
        data[f"bands-{i}-max_income"] = high or ""
        data[f"bands-{i}-rate"] = rate
        data[f"bands-{i}-quick_deduction"] = quick
    return data


def test_admin_saves_a_valid_schedule(client, superuser):
    client.force_login(superuser)
    response = client.post(
        reverse("admin:rules_taxschedule_add"),
        schedule_post([("0", "5000", "0", "0"), ("5000.01", "", "0.10", "500")]),
    )
    assert response.status_code == 302, response.content.decode()[:1500]
    assert TaxSchedule.objects.get().bands.count() == 2


def test_admin_rejects_a_schedule_with_a_gap(client, superuser):
    client.force_login(superuser)
    response = client.post(
        reverse("admin:rules_taxschedule_add"),
        schedule_post([("0", "2000", "0", "0"), ("3000", "", "0.15", "300")]),
    )
    assert response.status_code == 200
    assert "gap or overlap" in response.content.decode()
    assert not TaxSchedule.objects.exists()


def test_admin_rejects_a_schedule_with_wrong_quick_deduction(client, superuser):
    client.force_login(superuser)
    response = client.post(
        reverse("admin:rules_taxschedule_add"),
        schedule_post([("0", "2000", "0", "0"), ("2000.01", "", "0.15", "250")]),
    )
    assert response.status_code == 200
    assert "not continuous" in response.content.decode()
    assert not TaxSchedule.objects.exists()


def test_admin_adds_a_rule_value_and_rejects_a_bad_one(client, superuser):
    client.force_login(superuser)
    url = reverse("admin:rules_rulevalue_add")
    ok = client.post(
        url,
        {"key": "transport_taxable", "value": "no", "effective_from": "2026-07-01", "note": "x"},
    )
    assert ok.status_code == 302
    bad = client.post(
        url,
        {"key": "pension_employee_rate", "value": "7", "effective_from": "2026-07-01", "note": ""},
    )
    assert bad.status_code == 200
    assert RuleValue.objects.count() == 1


# --- Roles ---------------------------------------------------------------------------


def user_with_role(role):
    call_command("sync_roles", "--strict", stdout=io.StringIO())
    user = User.objects.create_user(role, password=PASSWORD)
    user.groups.add(Group.objects.get(name=role))
    return User.objects.get(pk=user.pk)


def test_only_admins_can_change_rules_and_nobody_can_delete():
    admin = user_with_role("admin")
    assert admin.has_perm("rules.change_rulevalue") and admin.has_perm("rules.add_taxschedule")
    assert not admin.has_perm("rules.delete_rulevalue")
    assert not admin.has_perm("rules.delete_taxband")


def test_payroll_officers_and_auditors_can_only_view_rules():
    for role in ("payroll_officer", "auditor"):
        user = user_with_role(role)
        assert user.has_perm("rules.view_rulevalue") and user.has_perm("rules.view_taxschedule")
        assert not user.has_perm("rules.change_rulevalue")


def test_hr_managers_have_no_access_to_pay_rules():
    user = user_with_role("hr_manager")
    assert not user.has_perm("rules.view_rulevalue")
