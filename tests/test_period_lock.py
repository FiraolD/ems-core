"""Locked-month guard (no Django needed)."""
from datetime import date

import pytest

from core import period_lock


@pytest.fixture(autouse=True)
def clean_guards():
    saved = list(period_lock._guards)
    period_lock._guards.clear()
    yield
    period_lock._guards[:] = saved


def test_nothing_is_closed_without_guards():
    assert period_lock.is_closed(date(2026, 9, 1)) is False
    period_lock.ensure_open(date(2026, 9, 1))


def test_a_guard_closes_its_dates_with_a_helpful_message():
    period_lock.register(lambda d: (d.year, d.month) == (2026, 9))
    with pytest.raises(period_lock.PeriodClosed, match="September 2026 payroll is locked"):
        period_lock.ensure_open(date(2026, 9, 20), "Leave")
    period_lock.ensure_open(date(2026, 10, 1))


def test_a_range_is_checked_month_by_month_including_the_middle():
    period_lock.register(lambda d: (d.year, d.month) == (2026, 10))
    with pytest.raises(period_lock.PeriodClosed):
        period_lock.ensure_open_range(date(2026, 9, 25), date(2026, 11, 5))  # October is inside
    period_lock.ensure_open_range(date(2026, 11, 1), date(2026, 12, 31))


def test_range_crossing_the_year_end():
    period_lock.register(lambda d: (d.year, d.month) == (2027, 1))
    with pytest.raises(period_lock.PeriodClosed):
        period_lock.ensure_open_range(date(2026, 12, 20), date(2027, 1, 3))


def test_registering_the_same_guard_twice_keeps_one():
    def guard(d):
        return False

    period_lock.register(guard)
    period_lock.register(guard)
    assert period_lock._guards == [guard]
