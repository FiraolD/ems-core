"""PAYE uses the marginal rate and quick deduction, never a flat top rate."""
from decimal import Decimal

import pytest

from countries.et.tax import (
    Bracket,
    BracketError,
    calculate_bonus_tax,
    calculate_paye,
    default_brackets,
    select_bracket,
    validate_brackets,
)

BRACKETS = default_brackets()


def paye(income):
    return calculate_paye(income, BRACKETS).paye


@pytest.mark.parametrize(
    "income,expected",
    [
        (2000, "0.00"),
        (2000.01, "0.00"),
        (4000, "300.00"),
        (4000.01, "300.00"),
        (7000, "900.00"),
        (7000.01, "900.00"),
        (10000, "1650.00"),
        (10000.01, "1650.00"),
        (14000, "2850.00"),
        (14000.01, "2850.00"),
        (20000, "4950.00"),
    ],
)
def test_bracket_boundaries(income, expected):
    assert paye(income) == Decimal(expected)


def test_mid_band_values_worked_by_hand():
    assert paye("3000") == Decimal("150.00")   # 3000 x 15% - 300
    assert paye("5500") == Decimal("600.00")   # 5500 x 20% - 500
    assert paye("8500") == Decimal("1275.00")  # 8500 x 25% - 850
    assert paye("12000") == Decimal("2250.00")  # 12000 x 30% - 1350


def test_top_rate_is_not_applied_to_the_whole_salary():
    result = calculate_paye(20000, BRACKETS)
    assert result.paye == Decimal("4950.00")
    assert result.paye != Decimal("7000.00")  # 35% of the whole 20000
    assert result.rate == Decimal("0.35") and result.label == "35%"


def test_tax_never_falls_as_income_rises():
    last = Decimal("-1")
    for cents in range(0, 3_000_000, 997):  # 0.00 .. 30,000.00 in uneven steps
        current = paye(Decimal(cents) / 100)
        assert current >= last
        last = current


def test_zero_and_negative_income():
    assert paye(0) == Decimal("0.00")
    assert paye(-50) == Decimal("0.00")


def test_labels():
    assert calculate_paye(1500, BRACKETS).label == "0%"
    assert calculate_paye(3000, BRACKETS).label == "15%"
    assert calculate_paye(20000, BRACKETS).label == "35%"


def test_amounts_are_rounded_half_up_to_the_santim():
    # 4000.03 x 20% - 500 = 300.006
    assert paye("4000.03") == Decimal("300.01")


# --- Bonus ---------------------------------------------------------------------------


def test_bonus_is_taxed_by_the_increase_it_causes():
    result = calculate_bonus_tax(10000, 5000, BRACKETS)
    assert result.paye_without_bonus == Decimal("1650.00")
    assert result.paye_with_bonus == Decimal("3200.00")  # 15000 x 35% - 2050
    assert result.bonus_tax == Decimal("1550.00")
    assert result.net_bonus == Decimal("3450.00")
    assert result.taxable_with_bonus == Decimal("15000.00")


def test_bonus_that_stays_in_a_zero_band_costs_nothing():
    assert calculate_bonus_tax(500, 1000, BRACKETS).bonus_tax == Decimal("0.00")


def test_negative_bonus_is_treated_as_zero():
    result = calculate_bonus_tax(10000, -500, BRACKETS)
    assert result.bonus_amount == Decimal("0.00") and result.bonus_tax == Decimal("0.00")


# --- The schedule --------------------------------------------------------------------


def test_the_default_schedule_is_valid():
    validate_brackets(BRACKETS)


def _band(low, high, rate, quick):
    return Bracket(Decimal(low), None if high is None else Decimal(high), Decimal(rate), Decimal(quick))


def test_a_gap_between_bands_is_rejected():
    bad = [_band("0", "2000", "0", "0"), _band("2100", None, "0.15", "300")]
    with pytest.raises(BracketError, match="gap or overlap"):
        validate_brackets(bad)


def test_overlapping_bands_are_rejected():
    bad = [_band("0", "2000", "0", "0"), _band("1999.99", None, "0.15", "300")]
    with pytest.raises(BracketError, match="gap or overlap"):
        validate_brackets(bad)


def test_a_schedule_must_start_at_zero_and_end_open():
    with pytest.raises(BracketError, match="start at 0"):
        validate_brackets([_band("100", None, "0.1", "0")])
    with pytest.raises(BracketError, match="no upper limit"):
        validate_brackets([_band("0", "2000", "0", "0")])


def test_only_the_last_band_may_be_open():
    bad = [_band("0", None, "0", "0"), _band("2000.01", None, "0.15", "300")]
    with pytest.raises(BracketError, match="only the last band"):
        validate_brackets(bad)


def test_a_wrong_quick_deduction_is_caught():
    bad = [
        _band("0", "2000", "0", "0"),
        _band("2000.01", "4000", "0.15", "250"),  # should be 300
        _band("4000.01", None, "0.20", "500"),
    ]
    with pytest.raises(BracketError, match="not continuous"):
        validate_brackets(bad)


def test_a_falling_rate_is_caught():
    bad = [
        _band("0", "2000", "0.15", "0"),
        _band("2000.01", None, "0.10", "-100"),
    ]
    with pytest.raises(BracketError, match="lower than the band before"):
        validate_brackets(bad)


def test_an_empty_schedule_is_rejected():
    with pytest.raises(BracketError):
        validate_brackets([])
    with pytest.raises(BracketError):
        calculate_paye(1000, [])


def test_income_no_band_covers_is_an_error_not_zero_tax():
    closed = [_band("0", "2000", "0", "0")]
    with pytest.raises(BracketError, match="No tax bracket covers"):
        select_bracket(5000, closed)
    with pytest.raises(BracketError):
        calculate_paye(5000, closed)
