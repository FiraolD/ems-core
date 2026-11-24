from datetime import date
from decimal import Decimal

import pytest

from core.extensions.client import RULE_KEYS
from core.rules.resolve import RuleEntry, effective_overrides, in_force
from core.rules.schema import (
    LABELS,
    RuleValueError,
    parse_rule_text,
    rule_choices,
    store_rule_value,
)

# --- Parsing what an administrator types ---------------------------------------------


@pytest.mark.parametrize("text", ["yes", "YES", " true ", "1", "on"])
def test_yes_values(text):
    assert parse_rule_text("transport_taxable", text) is True


@pytest.mark.parametrize("text", ["no", "No", "false", "0", "off"])
def test_no_values(text):
    assert parse_rule_text("transport_taxable", text) is False


def test_unclear_yes_no_is_refused():
    with pytest.raises(RuleValueError, match="yes or no"):
        parse_rule_text("transport_taxable", "maybe")


def test_whole_numbers_within_limits():
    assert parse_rule_text("absence_divisor", "30") == 30
    assert parse_rule_text("absence_divisor", " 26 ") == 26
    for bad in ("0", "32", "30.5", "abc"):
        with pytest.raises(RuleValueError):
            parse_rule_text("absence_divisor", bad)


def test_rates_are_exact_decimals_between_zero_and_one():
    assert parse_rule_text("pension_employee_rate", "0.07") == Decimal("0.07")
    assert parse_rule_text("pension_employee_rate", "0") == Decimal("0")
    assert parse_rule_text("pension_employee_rate", "1") == Decimal("1")
    for bad in ("7", "-0.1", "1.01", "seven", "NaN", "Infinity"):
        with pytest.raises(RuleValueError):
            parse_rule_text("pension_employee_rate", bad)


def test_blank_and_unknown_are_refused():
    with pytest.raises(RuleValueError, match="Enter a value"):
        parse_rule_text("absence_divisor", "  ")
    with pytest.raises(RuleValueError, match="Unknown rule"):
        parse_rule_text("not_a_rule", "1")


@pytest.mark.parametrize(
    "key,value", [("transport_taxable", False), ("absence_divisor", 26), ("pension_employee_rate", Decimal("0.065"))]
)
def test_stored_text_round_trips(key, value):
    assert parse_rule_text(key, store_rule_value(value)) == value


def test_every_known_rule_has_a_plain_label_and_is_offered():
    assert set(LABELS) == set(RULE_KEYS)
    assert [key for key, _ in rule_choices()] == list(RULE_KEYS)


# --- Which value applies on a date ---------------------------------------------------

BASE = {"transport_taxable": True, "absence_divisor": 30}


def entry(key, value, y, m, d):
    return RuleEntry(key, value, date(y, m, d))


def test_no_entries_means_the_base_rules():
    assert effective_overrides(BASE, [], date(2026, 9, 30)) == BASE


def test_an_entry_overrides_the_base_from_its_start_date():
    entries = [entry("transport_taxable", False, 2026, 7, 1)]
    assert effective_overrides(BASE, entries, date(2026, 6, 30))["transport_taxable"] is True
    assert effective_overrides(BASE, entries, date(2026, 7, 1))["transport_taxable"] is False
    assert effective_overrides(BASE, entries, date(2026, 12, 31))["transport_taxable"] is False


def test_the_latest_started_entry_wins_whatever_the_order():
    entries = [
        entry("absence_divisor", 26, 2026, 9, 1),
        entry("absence_divisor", 28, 2026, 1, 1),
        entry("absence_divisor", 24, 2027, 1, 1),
    ]
    assert effective_overrides(BASE, entries, date(2026, 3, 31))["absence_divisor"] == 28
    assert effective_overrides(BASE, entries, date(2026, 9, 30))["absence_divisor"] == 26
    assert effective_overrides(BASE, entries, date(2027, 1, 1))["absence_divisor"] == 24


def test_a_rule_can_be_added_that_the_base_does_not_mention():
    out = effective_overrides({}, [entry("pension_min_days", 5, 2026, 1, 1)], date(2026, 2, 1))
    assert out == {"pension_min_days": 5}


def test_the_base_mapping_is_not_modified():
    base = dict(BASE)
    effective_overrides(base, [entry("transport_taxable", False, 2026, 1, 1)], date(2026, 2, 1))
    assert base == BASE


def test_in_force_picks_the_latest_started():
    class Item:
        def __init__(self, day):
            self.effective_from = day

    items = [Item(date(2025, 7, 1)), Item(date(2024, 1, 1)), Item(date(2999, 1, 1))]
    assert in_force(items, date(2026, 1, 1)).effective_from == date(2025, 7, 1)
    assert in_force(items, date(2023, 12, 31)) is None
    assert in_force([], date(2026, 1, 1)) is None
