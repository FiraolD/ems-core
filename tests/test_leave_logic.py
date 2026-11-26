"""Leave day counting, entitlement and balances (no Django needed)."""
from datetime import date
from decimal import Decimal as D

import pytest

from modules.leave import logic

SUN = 6


def test_working_days_skip_the_rest_day_and_holidays():
    # Mon 2026-09-07 .. Sun 2026-09-13: 6 working days, minus a Wednesday holiday = 5
    assert logic.count_leave_days(date(2026, 9, 7), date(2026, 9, 13), rest_day=SUN) == D(6)
    assert logic.count_leave_days(date(2026, 9, 7), date(2026, 9, 13), rest_day=SUN,
                                  holidays={date(2026, 9, 9)}) == D(5)


def test_half_day():
    assert logic.count_leave_days(date(2026, 9, 7), date(2026, 9, 7), rest_day=SUN, half_day=True) == D("0.5")
    with pytest.raises(logic.LeaveError):
        logic.count_leave_days(date(2026, 9, 7), date(2026, 9, 8), rest_day=SUN, half_day=True)


def test_bad_ranges_are_refused():
    with pytest.raises(logic.LeaveError, match="before"):
        logic.count_leave_days(date(2026, 9, 8), date(2026, 9, 7), rest_day=SUN)
    with pytest.raises(logic.LeaveError, match="calendar year"):
        logic.count_leave_days(date(2026, 12, 30), date(2027, 1, 2), rest_day=SUN)
    with pytest.raises(logic.LeaveError, match="rest day"):
        logic.count_leave_days(date(2026, 9, 13), date(2026, 9, 13), rest_day=SUN)  # a Sunday


def test_service_years_on_the_anniversary():
    hire = date(2020, 6, 15)
    assert logic.service_years(hire, date(2021, 6, 14)) == 0
    assert logic.service_years(hire, date(2021, 6, 15)) == 1
    assert logic.service_years(hire, date(2019, 1, 1)) == 0


def test_entitlement_grows_one_day_every_n_years():
    hire = date(2010, 1, 1)
    # 16 base, +1 per 2 completed years on 1 Jan: 2026 has 16 years -> +8
    assert logic.entitlement(D(16), 2, hire, 2026) == D(24)
    assert logic.entitlement(D(16), 0, hire, 2026) == D(16)  # growth switched off
    assert logic.entitlement(D(16), 2, hire, 2009) == D(0)


def test_first_year_is_prorated_by_remaining_months_to_the_half_day():
    # hired 1 July: 6 months of 12 -> 8.0; hired 1 Dec: 1/12 * 16 = 1.33 -> 1.5
    assert logic.entitlement(D(16), 2, date(2026, 7, 1), 2026) == D("8.0")
    assert logic.entitlement(D(16), 2, date(2026, 12, 1), 2026) == D("1.5")
    assert logic.entitlement(D(16), 2, date(2026, 7, 1), 2026, prorate_first_year=False) == D(16)


def test_balance_subtracts_leave_used_and_applies_adjustments():
    b = logic.balance_for(2026, base_days=D(16), extra_day_every_years=2, hire_date=date(2020, 1, 1),
                          used_by_year={2026: D(5)}, adjustments_by_year={2026: D(2)})
    assert (b.entitled, b.used, b.adjustments) == (D(19), D(5), D(2))  # 16 base + 3 (6 years served, one day per 2)
    assert b.remaining == D(16)


def test_unused_days_carry_over_up_to_the_cap():
    kw = dict(base_days=D(16), extra_day_every_years=0, hire_date=date(2025, 1, 1),
              used_by_year={2025: D(6)}, adjustments_by_year={})
    capped = logic.balance_for(2026, carry_over_max=D(5), **kw)
    assert capped.carried_in == D(5) and capped.remaining == D(21)
    none = logic.balance_for(2026, carry_over_max=D(0), **kw)
    assert none.carried_in == D(0) and none.remaining == D(16)


def test_overspending_does_not_create_negative_carry():
    b = logic.balance_for(2026, base_days=D(10), extra_day_every_years=0, hire_date=date(2025, 1, 1),
                          used_by_year={2025: D(14)}, adjustments_by_year={}, carry_over_max=D(5))
    assert b.carried_in == D(0)


def test_overlap():
    a = (date(2026, 9, 1), date(2026, 9, 5))
    assert logic.overlaps(*a, date(2026, 9, 5), date(2026, 9, 9))
    assert not logic.overlaps(*a, date(2026, 9, 6), date(2026, 9, 9))
