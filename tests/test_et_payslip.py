"""Whole-payslip figures. Expected values were worked out by hand from the rules, not by
running the code, so a mistake in the code cannot hide behind a copy of itself."""
import json
from datetime import date
from decimal import Decimal

import pytest

from countries import UnknownCountryPack, get_pack
from countries.et import (
    PayRules,
    PayslipInput,
    compute_payslip,
    default_brackets,
    resolve_rules,
    rules_snapshot,
)
from countries.et.absence import DayRecord

BRACKETS = default_brackets()
SEP_1, SEP_30 = date(2026, 9, 1), date(2026, 9, 30)
OLD_HIRE = date(2020, 1, 1)


def slip(rules=None, **values):
    values.setdefault("period_start", SEP_1)
    values.setdefault("period_end", SEP_30)
    values.setdefault("hire_date", OLD_HIRE)
    return compute_payslip(PayslipInput(**values), rules or PayRules(), BRACKETS)


def d(value):
    return Decimal(value)


def test_plain_month():
    p = slip(basic_salary=d("10000"), transport_allowance=d("600"))
    # taxable 10600 -> 10600 x 30% - 1350 = 1830; pension 7% / 11% of 10000
    assert p.taxable_income == d("10600.00")
    assert p.tax.paye == d("1830.00")
    assert p.pension.employee_contribution == d("700.00")
    assert p.pension.employer_contribution == d("1100.00")
    assert p.gross_earnings == d("10600.00")
    assert p.total_deductions == d("2530.00")
    assert p.net_salary == d("8070.00")
    assert p.employer_cost == d("11700.00")
    assert p.warnings == ()


def test_exempt_transport_lowers_the_tax():
    p = slip(PayRules(transport_taxable=False), basic_salary=d("10000"), transport_allowance=d("600"))
    # taxable 10000 -> 10000 x 25% - 850 = 1650
    assert p.taxable_income == d("10000.00")
    assert p.tax.paye == d("1650.00")
    assert p.net_salary == d("8250.00")  # 10600 - 1650 - 700


def test_absence_and_leave():
    p = slip(
        basic_salary=d("9000"),
        transport_allowance=d("600"),
        attendance=[DayRecord(date(2026, 9, 1), "absent"), DayRecord(date(2026, 9, 2), "annual_leave")],
    )
    # basic deduction 300; transport 600/30 x 2 = 40 -> 560 paid; gross 9560
    # taxable 9000 - 300 + 560 = 9260 -> 9260 x 25% - 850 = 1465
    # pension on 8700: 609.00 employee, 957.00 employer
    assert p.absence.basic_deduction == d("300.00")
    assert p.transport_payable == d("560.00")
    assert p.gross_earnings == d("9560.00")
    assert p.taxable_income == d("9260.00")
    assert p.tax.paye == d("1465.00")
    assert p.pensionable_salary == d("8700.00")
    assert (p.pension.employee_contribution, p.pension.employer_contribution) == (
        d("609.00"),
        d("957.00"),
    )
    assert p.total_deductions == d("2374.00")  # 1465 + 609 + 300
    assert p.net_salary == d("7186.00")
    assert p.employer_cost == d("10517.00")


def test_taxable_bonus():
    p = slip(basic_salary=d("10000"), bonus=d("5000"))
    # PAYE on 15000 = 15000 x 35% - 2050 = 3200; on 10000 = 1650; bonus tax 1550
    assert p.taxable_income == d("15000.00")
    assert p.tax.paye == d("3200.00")
    assert p.bonus_tax == d("1550.00")
    assert p.gross_earnings == d("15000.00")
    assert p.net_salary == d("11100.00")  # 15000 - 3200 - 700


def test_untaxed_bonus_is_paid_but_not_taxed():
    p = slip(PayRules(bonus_taxable=False), basic_salary=d("10000"), bonus=d("5000"))
    assert p.tax.paye == d("1650.00") and p.bonus_tax == d("0.00")
    assert p.gross_earnings == d("15000.00")
    assert p.net_salary == d("12650.00")  # 15000 - 1650 - 700


def test_non_taxable_other_allowance():
    taxable = slip(basic_salary=d("5000"), other_allowances=d("1000"))
    exempt = slip(basic_salary=d("5000"), other_allowances=d("1000"), other_allowances_taxable=False)
    assert taxable.tax.paye == d("700.00")  # 6000 x 20% - 500
    assert exempt.tax.paye == d("500.00")   # 5000 x 20% - 500
    assert taxable.gross_earnings == exempt.gross_earnings == d("6000.00")


def test_overtime_is_taxable_by_default_and_switchable():
    on = slip(basic_salary=d("5000"), overtime_pay=d("1000"))
    off = slip(PayRules(ot_taxable=False), basic_salary=d("5000"), overtime_pay=d("1000"))
    assert on.tax.paye == d("700.00") and off.tax.paye == d("500.00")
    assert on.gross_earnings == off.gross_earnings == d("6000.00")


def test_new_hire_pension_rule_flows_through():
    p = slip(basic_salary=d("3000"), hire_date=date(2026, 9, 21))
    assert (p.pension_service_days, p.pension_prorated) == (10, True)
    assert p.pensionable_salary == d("1000.00")
    assert p.pension.employee_contribution == d("70.00")
    short = slip(basic_salary=d("3000"), hire_date=date(2026, 9, 22))
    assert short.pension.employee_contribution == d("0.00")


def test_salary_advance_is_deducted_from_net_only():
    plain = slip(basic_salary=d("5000"))
    advanced = slip(basic_salary=d("5000"), salary_advance=d("1000"))
    assert advanced.tax.paye == plain.tax.paye
    assert advanced.pension == plain.pension
    assert advanced.net_salary == plain.net_salary - d("1000.00")


def test_a_net_below_zero_is_flagged_not_hidden():
    p = slip(basic_salary=d("1000"), salary_advance=d("5000"))
    assert p.net_salary == d("-4070.00")  # 1000 - 0 tax - 70 pension - 5000
    assert p.warnings == ("net_salary_is_negative",)


def test_a_client_rule_override_changes_the_result():
    custom = resolve_rules({"pension_employee_rate": d("0.05"), "pension_employer_rate": d("0.10")})
    p = slip(custom, basic_salary=d("10000"))
    assert p.pension.employee_contribution == d("500.00")
    assert p.pension.employer_contribution == d("1000.00")


def test_zero_salary_gives_zero_everything():
    p = slip(basic_salary=d("0"))
    assert p.gross_earnings == p.net_salary == p.tax.paye == d("0.00")


def test_results_are_identical_when_repeated():
    kwargs = {"basic_salary": d("12345.67"), "transport_allowance": d("800"), "bonus": d("2000")}
    assert slip(**kwargs) == slip(**kwargs)


# --- Rules and packs -----------------------------------------------------------------


def test_default_rules_match_the_old_system():
    rules = resolve_rules()
    assert rules.absence_divisor == 30 and rules.pension_min_days == 10
    assert rules.pension_employee_rate == d("0.07") and rules.pension_employer_rate == d("0.11")
    assert rules.transport_taxable and rules.ot_taxable and rules.bonus_taxable


def test_unknown_override_is_refused():
    with pytest.raises(ValueError, match="Unknown pay rule"):
        resolve_rules({"pension_rate": d("0.07")})


def test_client_config_overrides_are_understood_by_the_pack():
    from core.extensions.client import RULE_KEYS

    assert set(RULE_KEYS) <= set(PayRules.__dataclass_fields__)


def test_snapshot_is_plain_json_and_records_the_schedule():
    snapshot = rules_snapshot(resolve_rules(), BRACKETS)
    loaded = json.loads(json.dumps(snapshot))
    assert loaded["pension_employee_rate"] == "0.07"
    assert loaded["tax_brackets"][-1] == {
        "min_income": "14000.01",
        "max_income": None,
        "rate": "0.35",
        "quick_deduction": "2050",
    }


def test_the_ethiopia_pack_is_found_by_code():
    pack = get_pack("et")
    assert (pack.CODE, pack.CURRENCY) == ("et", "ETB")
    assert pack.compute_payslip is compute_payslip


@pytest.mark.parametrize("code", ["xx", "ET", "../x", "e", "etc", ""])
def test_unknown_or_malformed_packs_are_refused(code):
    with pytest.raises(UnknownCountryPack):
        get_pack(code)
