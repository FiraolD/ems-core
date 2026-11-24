from dataclasses import dataclass
from datetime import date

import pytest

from modules.hr.rules import eligible_for_period, record_on

START, END = date(2026, 3, 1), date(2026, 3, 31)


def test_working_employee_is_eligible():
    assert eligible_for_period(date(2020, 1, 1), "active", None, START, END)
    assert eligible_for_period(date(2020, 1, 1), "on_leave", None, START, END)


def test_hired_after_the_period_is_not_eligible():
    assert not eligible_for_period(date(2026, 4, 1), "active", None, START, END)


def test_hired_on_the_last_day_is_eligible():
    assert eligible_for_period(END, "active", None, START, END)


def test_suspended_is_not_eligible():
    assert not eligible_for_period(date(2020, 1, 1), "suspended", None, START, END)


@pytest.mark.parametrize("status", ["resigned", "terminated", "retired"])
def test_leaver_before_the_period_is_not_eligible(status):
    assert not eligible_for_period(date(2020, 1, 1), status, date(2026, 2, 28), START, END)


@pytest.mark.parametrize("status", ["resigned", "terminated", "retired"])
def test_leaver_during_or_on_the_first_day_is_still_eligible(status):
    assert eligible_for_period(date(2020, 1, 1), status, date(2026, 3, 15), START, END)
    assert eligible_for_period(date(2020, 1, 1), status, START, START, END)


def test_leaver_without_a_date_stays_on_the_payroll():
    assert eligible_for_period(date(2020, 1, 1), "resigned", None, START, END)


def test_backwards_period_is_an_error():
    with pytest.raises(ValueError):
        eligible_for_period(date(2020, 1, 1), "active", None, END, START)


@dataclass
class Rec:
    effective_date: date
    basic: int


def test_record_on_picks_latest_effective_not_after_the_date():
    recs = [Rec(date(2025, 1, 1), 100), Rec(date(2026, 1, 1), 200), Rec(date(2026, 6, 1), 300)]
    assert record_on(recs, date(2026, 3, 31)).basic == 200
    assert record_on(recs, date(2026, 6, 1)).basic == 300
    assert record_on(recs, date(2025, 1, 1)).basic == 100


def test_record_on_ignores_input_order():
    recs = [Rec(date(2026, 6, 1), 300), Rec(date(2025, 1, 1), 100), Rec(date(2026, 1, 1), 200)]
    assert record_on(recs, date(2026, 3, 31)).basic == 200


def test_record_on_before_any_record_is_none():
    assert record_on([Rec(date(2026, 1, 1), 1)], date(2025, 12, 31)) is None
    assert record_on([], date(2026, 1, 1)) is None
