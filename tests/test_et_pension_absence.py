"""Pension (7% / 11%, new-hire rule) and absence deductions on a 30-day month."""
from datetime import date
from decimal import Decimal

import pytest

from countries.et.absence import DayRecord, compute_absence, daily_rate
from countries.et.pension import calculate_pension, pension_base, service_days

SEP_1, SEP_30 = date(2026, 9, 1), date(2026, 9, 30)


# --- Pension -------------------------------------------------------------------------


def test_rates_are_seven_and_eleven():
    result = calculate_pension(10000)
    assert result.employee_contribution == Decimal("700.00")
    assert result.employer_contribution == Decimal("1100.00")


def test_employer_pension_does_not_reduce_net_pay():
    result = calculate_pension(Decimal("10000"))
    assert Decimal("10000.00") - result.employee_contribution == Decimal("9300.00")


def test_negative_pensionable_pay_is_treated_as_zero():
    assert calculate_pension(-5).employee_contribution == Decimal("0.00")


def test_contributions_round_half_up():
    # 7% of 1000.50 = 70.035 -> 70.04; 11% = 110.055 -> 110.06
    result = calculate_pension("1000.50")
    assert result.employee_contribution == Decimal("70.04")
    assert result.employer_contribution == Decimal("110.06")


def test_new_hire_under_ten_days_has_no_pension():
    base = pension_base(Decimal("3000"), date(2026, 9, 22), SEP_1, SEP_30)
    assert (base.service_days, base.prorated, base.pensionable) == (9, True, Decimal("0.00"))
    result = calculate_pension(base.pensionable)
    assert result.employee_contribution == result.employer_contribution == Decimal("0.00")


def test_new_hire_with_ten_days_is_prorated():
    base = pension_base(Decimal("3000"), date(2026, 9, 21), SEP_1, SEP_30)
    assert (base.service_days, base.prorated, base.pensionable) == (10, True, Decimal("1000.00"))
    result = calculate_pension(base.pensionable)
    assert result.employee_contribution == Decimal("70.00")
    assert result.employer_contribution == Decimal("110.00")


def test_hire_on_the_first_is_a_full_month():
    base = pension_base(Decimal("5000"), date(2026, 9, 1), SEP_1, SEP_30)
    assert base.prorated is False and base.service_days is None
    assert base.pensionable == Decimal("5000.00")


def test_continuing_employee_pension_follows_earned_basic():
    base = pension_base(
        Decimal("10000"), date(2020, 1, 1), SEP_1, SEP_30, absence_deduction=Decimal("1000")
    )
    assert base.prorated is False and base.pensionable == Decimal("9000.00")


def test_absence_cannot_push_pensionable_pay_below_zero():
    base = pension_base(1000, date(2020, 1, 1), SEP_1, SEP_30, absence_deduction=5000)
    assert base.pensionable == Decimal("0.00")


def test_proration_never_exceeds_the_full_basic():
    # A 31-day month with a divisor of 20 would otherwise give 31/20 of basic.
    base = pension_base(1000, date(2026, 10, 2), date(2026, 10, 1), date(2026, 10, 31), divisor=20)
    assert base.pensionable == Decimal("1000.00")


def test_service_days_counts_the_hire_day():
    assert service_days(date(2026, 9, 30), SEP_1, SEP_30) == 1
    assert service_days(date(2026, 10, 1), SEP_1, SEP_30) == 0
    assert service_days(date(2020, 1, 1), SEP_1, SEP_30) == 30


# --- Absence -------------------------------------------------------------------------


def day(d, status):
    return DayRecord(date(2026, 9, d), status)


def test_paid_leave_reduces_transport_only():
    result = compute_absence(
        [day(1, "absent"), day(2, "annual_leave"), day(3, "sick_leave")], 9000, 600, divisor=30
    )
    assert result.unpaid_days == Decimal("1")
    assert result.leave_transport_days == Decimal("2")
    assert result.basic_deduction == Decimal("300.00")
    assert result.transport_deduction == Decimal("60.00")


def test_same_date_is_not_deducted_twice():
    result = compute_absence([day(1, "absent"), day(1, "unpaid_leave")], 3000, 0)
    assert result.unpaid_days == Decimal("1")
    assert result.basic_deduction == Decimal("100.00")


def test_half_day_is_half_a_basic_day():
    result = compute_absence([day(4, "half_day")], 9000, 300)
    assert result.unpaid_days == Decimal("0.5")
    assert result.basic_deduction == Decimal("150.00")
    assert result.transport_deduction == Decimal("5.00")


def test_present_and_holiday_are_not_deducted():
    result = compute_absence(
        [day(1, "present"), day(2, "public_holiday"), day(3, "weekly_rest_day")], 9000, 600
    )
    assert result.unpaid_days == result.leave_transport_days == Decimal("0")
    assert result.basic_deduction == result.transport_deduction == Decimal("0.00")
    assert result.dates == []


def test_an_absence_beats_paid_leave_on_the_same_day():
    result = compute_absence([day(1, "annual_leave"), day(1, "absent")], 3000, 0)
    assert result.unpaid_days == Decimal("1") and result.leave_transport_days == Decimal("0")


def test_deductions_never_exceed_the_amount_they_come_from():
    # 31 absent days against a 30-day divisor would be 31/30 of the pay without the cap.
    many = [DayRecord(date(2026, 8, d), "absent") for d in range(1, 32)]
    result = compute_absence(many, 3000, 300)
    assert result.basic_deduction == Decimal("3000.00")
    assert result.transport_deduction == Decimal("300.00")


def test_touched_dates_are_listed_in_order():
    result = compute_absence([day(5, "absent"), day(2, "annual_leave")], 3000, 0)
    assert result.dates == [date(2026, 9, 2), date(2026, 9, 5)]


def test_divisor_must_be_positive():
    with pytest.raises(ValueError):
        daily_rate(3000, 0)
