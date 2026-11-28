"""The second sample client, tested without Django.

Figures are worked by hand: basic 12000, transport 600, September 2026, two absent days.
  template  (30-day month, transport taxable):   absence 12000/30 x 2 = 800.00
                                                 taxable 12560 - 800 = 11760; PAYE 11760 x 30% - 1350 = 2178.00
  workshop  (26-day month, transport exempt):    absence 12000/26 x 2 = 923.08
                                                 taxable 12000 - 923.08 = 11076.92; PAYE x 30% - 1350 = 1973.08
"""
import sys
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

import pytest

import countries
from core.extensions.client import ClientConfigError, load_client_config
from core.extensions.registry import HookRegistry

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "clients" / "_template" / "client.toml"
WORKSHOP = ROOT / "clients" / "_sample_workshop" / "client.toml"

sys.path.insert(0, str(WORKSHOP.parent))
import workshop_extension as ext  # noqa: E402  (the sample client's own package)

et = countries.get_pack("et")
SEPT = (date(2026, 9, 1), date(2026, 9, 30))


def payslip(config, *, absent_days=0, bonus="0"):
    attendance = [et.DayRecord(date(2026, 9, d), "absent") for d in range(1, 1 + absent_days)]
    return et.compute_payslip(
        et.PayslipInput(
            period_start=SEPT[0], period_end=SEPT[1], basic_salary=D("12000"), transport_allowance=D("600"),
            other_allowances=D("0"), other_allowances_taxable=True, overtime_pay=D("0"), bonus=D(bonus),
            salary_advance=D("0"), hire_date=date(2020, 1, 1), termination_date=None, attendance=attendance,
        ),
        et.resolve_rules(dict(config.rule_overrides)),
        et.default_brackets(),
    )


# --- The two configurations differ -----------------------------------------------------


def test_both_clients_load_and_are_different_installs():
    template, workshop = load_client_config(TEMPLATE), load_client_config(WORKSHOP)
    assert template.slug != workshop.slug
    assert "leave" in template.enabled_modules and "overtime" in template.enabled_modules
    assert workshop.enabled_modules == ("hr", "attendance", "payroll")
    assert dict(template.rule_overrides) == {}
    assert dict(workshop.rule_overrides) == {"absence_divisor": 26, "transport_taxable": False}
    assert dict(workshop.extension_settings) == {"full_attendance_bonus": "500.00"}
    assert workshop.extension_package == "workshop_extension"


def test_same_employee_same_absences_pays_differently_under_each_clients_rules():
    template, workshop = load_client_config(TEMPLATE), load_client_config(WORKSHOP)
    a, b = payslip(template, absent_days=2), payslip(workshop, absent_days=2)
    assert (a.absence.basic_deduction, a.taxable_income, a.tax.paye, a.net_salary) == (
        D("800.00"), D("11760.00"), D("2178.00"), D("8798.00"))
    assert (b.absence.basic_deduction, b.taxable_income, b.tax.paye, b.net_salary) == (
        D("923.08"), D("11076.92"), D("1973.08"), D("8882.30"))


def test_a_bonus_is_taxed_inside_paye_under_both_clients():
    template, workshop = load_client_config(TEMPLATE), load_client_config(WORKSHOP)
    t, w = payslip(template, bonus="500.00"), payslip(workshop, bonus="500.00")
    assert (t.tax.paye, t.bonus_tax, t.net_salary) == (D("2580.00"), D("150.00"), D("9680.00"))
    assert (w.tax.paye, w.bonus_tax, w.net_salary) == (D("2400.00"), D("150.00"), D("9860.00"))
    # net = gross - PAYE - pension (bonus tax is not taken a second time)
    assert w.net_salary == w.gross_earnings - w.tax.paye - w.pension.employee_contribution


# --- The workshop extension ---------------------------------------------------------------


def employee(hired=date(2020, 1, 1), left=None):
    return SimpleNamespace(employment_date=hired, termination_date=left)


def inputs(*statuses):
    return SimpleNamespace(
        bonus=D("0"), attendance=[SimpleNamespace(status=s, day=date(2026, 9, 1)) for s in statuses]
    )


def run_hook(emp, *statuses, amount=D("500.00")):
    hook = ext.make_hook(amount)
    return hook(inputs(*statuses), employee=emp, period_start=SEPT[0], period_end=SEPT[1]).bonus


def test_full_attendance_earns_the_bonus():
    assert run_hook(employee()) == D("500.00")


@pytest.mark.parametrize("status", ["absent", "half_day", "unpaid_leave"])
def test_any_unpaid_absence_loses_it(status):
    assert run_hook(employee(), status) == D("0")


def test_paid_leave_does_not_count_against_the_employee():
    assert run_hook(employee(), "annual_leave", "sick_leave") == D("500.00")


def test_joiners_and_leavers_in_the_month_do_not_get_it():
    assert run_hook(employee(hired=date(2026, 9, 2))) == D("0")
    assert run_hook(employee(left=date(2026, 9, 20))) == D("0")
    assert run_hook(employee(hired=date(2026, 9, 1))) == D("500.00")  # worked the whole month


def test_it_adds_to_a_bonus_already_approved():
    hook = ext.make_hook(D("500.00"))
    data = inputs()
    data.bonus = D("1000")
    assert hook(data, employee=employee(), period_start=SEPT[0], period_end=SEPT[1]).bonus == D("1500.00")


def test_a_zero_amount_turns_the_bonus_off():
    assert run_hook(employee(), amount=D("0")) == D("0")


def test_the_amount_must_be_a_valid_non_negative_money_value():
    assert ext.parse_amount("500.00") == D("500.00")
    for bad in ("lots", "-1", "NaN", "Infinity"):
        with pytest.raises(ClientConfigError):
            ext.parse_amount(bad)


def test_register_attaches_the_hook_after_the_modules_own_inputs(monkeypatch):
    registry = HookRegistry()
    registry.declare(ext.HOOK)
    settings = SimpleNamespace(EMS_CLIENT=SimpleNamespace(has_module=lambda name: True))
    monkeypatch.setitem(sys.modules, "django", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "django.conf", SimpleNamespace(settings=settings))
    monkeypatch.setattr(ext, "_configured_amount", lambda: D("750.00"))
    # modules.payroll.inputs needs only the registry, so the real one is declared for us
    ext.register(registry)
    names = [fn.__name__ for fn in registry.functions(ext.HOOK)]
    assert names[-1] == "add_full_attendance_bonus"
