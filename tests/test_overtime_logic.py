"""Overtime validation and pay arithmetic (no Django needed)."""
from datetime import date
from decimal import Decimal as D

import pytest

from modules.overtime import logic

SUN = 6
MON = date(2026, 9, 7)
SUNDAY = date(2026, 9, 13)
HOLIDAY_DAY = date(2026, 9, 9)  # a Wednesday


def check(kind, day, hours="2", holidays=frozenset()):
    return logic.validate_entry(kind, day, hours, rest_day=SUN, holidays=holidays)


def test_ordinary_days_take_normal_or_night():
    assert check("normal", MON) == D("2")
    assert check("night", MON) == D("2")


def test_rest_day_and_holiday_force_their_category():
    with pytest.raises(logic.OvertimeError, match="weekly rest day"):
        check("normal", SUNDAY)
    with pytest.raises(logic.OvertimeError, match="public holiday"):
        check("night", HOLIDAY_DAY, holidays={HOLIDAY_DAY})
    assert check("rest_day", SUNDAY) == D("2")
    assert check("public_holiday", HOLIDAY_DAY, holidays={HOLIDAY_DAY}) == D("2")


def test_a_holiday_on_the_rest_day_counts_as_a_holiday():
    assert logic.required_kind(SUNDAY, rest_day=SUN, holidays={SUNDAY}) == "public_holiday"


def test_wrong_special_category_is_refused():
    with pytest.raises(logic.OvertimeError, match="not the weekly rest day"):
        check("rest_day", MON)
    with pytest.raises(logic.OvertimeError, match="not a public holiday"):
        check("public_holiday", MON)


def test_hours_must_be_sensible():
    for bad in ("0", "-1", "17", "abc", "NaN", "Infinity", ""):
        with pytest.raises(logic.OvertimeError):
            check("normal", MON, bad)


def test_hourly_rate_uses_the_pay_rule_divisor():
    assert logic.hourly_rate(D("12000"), 30, 8) == D("50")
    with pytest.raises(ValueError):
        logic.hourly_rate(D("12000"), 0, 8)


def test_pay_is_hourly_rate_times_weighted_hours():
    # basic 12000 -> 50/hour. 2h x 1.25 + 3h x 2.0 = 8.5 weighted hours -> 425.00
    entries = [(D("2"), D("1.25")), (D("3"), D("2.0"))]
    assert logic.weighted_hours(entries) == D("8.5")
    assert logic.overtime_pay(D("12000"), entries, 30, 8) == D("425.00")


def test_rounding_happens_once_at_the_end():
    # basic 10000 -> 41.6666.../hour. Three one-hour entries at 1.25: 3.75 weighted hours = 156.25
    entries = [(D("1"), D("1.25"))] * 3
    assert logic.overtime_pay(D("10000"), entries, 30, 8) == D("156.25")


def test_no_entries_is_zero():
    assert logic.overtime_pay(D("12000"), [], 30, 8) == D("0.00")
