"""Ethiopian employment income tax (PAYE): taxable income x marginal rate - quick deduction.

The quick deduction makes the schedule progressive: only the part of income inside each band
is taxed at that band's rate, so the top rate is never applied to the whole salary.

No Django imports.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from core.money import CENT, D, money


class BracketError(ValueError):
    """The tax schedule is malformed, or does not cover the income being taxed."""


@dataclass(frozen=True)
class Bracket:
    min_income: Decimal
    max_income: Decimal | None  # None: no upper limit (top band). Upper bounds are inclusive.
    rate: Decimal
    quick_deduction: Decimal


@dataclass(frozen=True)
class TaxResult:
    taxable_income: Decimal
    rate: Decimal
    quick_deduction: Decimal
    paye: Decimal
    label: str


def _covers(income: Decimal, bracket: Bracket) -> bool:
    if income < D(bracket.min_income):
        return False
    return bracket.max_income is None or income <= D(bracket.max_income)


def select_bracket(taxable_income, brackets: Sequence[Bracket]) -> Bracket:
    income = money(taxable_income)
    if not brackets:
        raise BracketError("No tax brackets are configured")
    for bracket in sorted(brackets, key=lambda item: D(item.min_income)):
        if _covers(income, bracket):
            return bracket
    # Falling back to the first band here would silently tax a high earner at 0%.
    raise BracketError(f"No tax bracket covers an income of {income}")


def validate_brackets(brackets: Sequence[Bracket]) -> None:
    """Check a schedule is safe to use. Raises ``BracketError`` listing every problem.

    - starts at 0, and each band begins one santim after the previous one ends
    - only the last band is open-ended
    - rates are between 0 and 1 and never fall as income rises
    - quick deductions make the tax continuous: at each boundary the old and new band give
      the same tax to within one santim (otherwise earning 1 santim more could change tax
      by a visible amount)
    """
    problems: list[str] = []
    ordered = sorted(brackets, key=lambda item: D(item.min_income))
    if not ordered:
        raise BracketError("No tax brackets are configured")
    if D(ordered[0].min_income) != 0:
        problems.append("the first band must start at 0")
    for index, band in enumerate(ordered):
        low, rate_ = D(band.min_income), D(band.rate)
        if not 0 <= rate_ <= 1:
            problems.append(f"band from {low}: rate must be between 0 and 1")
        if band.max_income is None:
            if index != len(ordered) - 1:
                problems.append(f"band from {low}: only the last band can be open-ended")
            continue
        high = D(band.max_income)
        if high < low:
            problems.append(f"band from {low}: upper limit {high} is below the lower limit")
        if index == len(ordered) - 1:
            problems.append("the last band must have no upper limit")
            continue
        nxt = ordered[index + 1]
        if D(nxt.min_income) != high + CENT:
            problems.append(
                f"band ending {high} and band starting {D(nxt.min_income)} leave a gap or overlap"
            )
        if D(nxt.rate) < rate_:
            problems.append(f"band from {D(nxt.min_income)}: rate is lower than the band before")
        before = high * rate_ - D(band.quick_deduction)
        after = high * D(nxt.rate) - D(nxt.quick_deduction)
        if abs(before - after) > CENT:
            problems.append(
                f"tax is not continuous at {high}: {before} before, {after} after the boundary"
            )
    if problems:
        raise BracketError("Invalid tax schedule: " + "; ".join(problems))


def calculate_paye(taxable_income, brackets: Sequence[Bracket]) -> TaxResult:
    """PAYE = taxable income x marginal rate - quick deduction (never below zero)."""
    income = money(taxable_income)
    if income <= 0:
        return TaxResult(money(0), D(0), money(0), money(0), "0%")
    bracket = select_bracket(income, brackets)
    raw = income * D(bracket.rate) - D(bracket.quick_deduction)
    return TaxResult(
        taxable_income=income,
        rate=D(bracket.rate),
        quick_deduction=money(bracket.quick_deduction),
        paye=money(raw) if raw > 0 else money(0),
        label=f"{D(bracket.rate) * 100:.0f}%",
    )


@dataclass(frozen=True)
class BonusTaxResult:
    """Tax on a bonus, by the incremental method used by the old system.

    The bonus is income for the month. Tax for the month is PAYE on (regular taxable income
    + bonus); the bonus' share is the increase it causes: PAYE(with) - PAYE(without).
    """

    bonus_amount: Decimal
    taxable_without_bonus: Decimal
    taxable_with_bonus: Decimal
    paye_without_bonus: Decimal
    paye_with_bonus: Decimal
    bonus_tax: Decimal
    net_bonus: Decimal
    tax_label: str


def calculate_bonus_tax(
    taxable_without_bonus, bonus_amount, brackets: Sequence[Bracket]
) -> BonusTaxResult:
    base = money(taxable_without_bonus)
    bonus = max(money(bonus_amount), money(0))
    without = calculate_paye(base, brackets)
    with_bonus = calculate_paye(base + bonus, brackets)
    bonus_tax = max(money(with_bonus.paye - without.paye), money(0))
    return BonusTaxResult(
        bonus_amount=bonus,
        taxable_without_bonus=base,
        taxable_with_bonus=with_bonus.taxable_income,
        paye_without_bonus=without.paye,
        paye_with_bonus=with_bonus.paye,
        bonus_tax=bonus_tax,
        net_bonus=money(bonus - bonus_tax),
        tax_label=with_bonus.label,
    )


# Schedule supplied by the client for the old system: bands in birr per month. Upper bounds
# are inclusive and the next band starts one santim later.
_ET_ROWS = (
    ("0", "2000", "0", "0"),
    ("2000.01", "4000", "0.15", "300"),
    ("4000.01", "7000", "0.20", "500"),
    ("7000.01", "10000", "0.25", "850"),
    ("10000.01", "14000", "0.30", "1350"),
    ("14000.01", None, "0.35", "2050"),
)


def default_brackets() -> tuple[Bracket, ...]:
    return tuple(
        Bracket(D(low), None if high is None else D(high), D(pct), D(quick))
        for low, high, pct, quick in _ET_ROWS
    )
