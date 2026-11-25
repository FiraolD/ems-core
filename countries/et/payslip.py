"""One employee's pay for one month, calculated from plain facts.

This is the statutory heart of payroll and does not touch a database: the payroll module
gathers the facts (salary, attendance, overtime, bonus), calls ``compute_payslip`` and stores
the result. Same facts and rules in, same figures out.

No Django imports.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from core.money import money

from .absence import AbsenceResult, DayRecord, compute_absence
from .pension import PensionResult, calculate_pension
from .rules import PayRules
from .tax import Bracket, TaxResult, calculate_bonus_tax, calculate_paye


@dataclass(frozen=True)
class PayslipInput:
    period_start: date
    period_end: date
    basic_salary: Decimal
    transport_allowance: Decimal = Decimal("0")
    other_allowances: Decimal = Decimal("0")
    other_allowances_taxable: bool = True
    overtime_pay: Decimal = Decimal("0")
    bonus: Decimal = Decimal("0")
    salary_advance: Decimal = Decimal("0")
    hire_date: date | None = None
    termination_date: date | None = None  # set for someone who has left
    attendance: Sequence[DayRecord] = ()  # absences and paid leave inside the period


@dataclass(frozen=True)
class Payslip:
    basic_salary: Decimal  # the agreed monthly basic
    basic_earned: Decimal  # basic for this month: prorated when only part of it was worked
    days_worked: int | None  # set only when the month was part-worked (hired or left in it)
    transport_payable: Decimal  # transport after the leave and absence deduction
    other_allowances: Decimal
    overtime_pay: Decimal
    bonus: Decimal
    gross_earnings: Decimal
    absence: AbsenceResult
    taxable_income: Decimal  # what PAYE was charged on, bonus included
    tax: TaxResult
    bonus_tax: Decimal
    pensionable_salary: Decimal
    pension_service_days: int | None
    pension_prorated: bool
    pension: PensionResult
    salary_advance: Decimal
    total_deductions: Decimal
    net_salary: Decimal
    employer_cost: Decimal
    warnings: tuple[str, ...] = field(default=())


def compute_payslip(
    data: PayslipInput, rules: PayRules, brackets: Sequence[Bracket]
) -> Payslip:
    basic = money(data.basic_salary)
    transport = money(data.transport_allowance)
    other = money(data.other_allowances)
    overtime = money(data.overtime_pay)
    bonus = max(money(data.bonus), money(0))
    advance = money(data.salary_advance)

    absence = compute_absence(data.attendance, basic, transport, rules.absence_divisor)

    # Part-month work. Someone hired during the month is always paid from their hire date.
    # Someone who left during it is paid to their leaving date only when the rules say so
    # (prorate_leavers). Both use the same 30-day company month as absence and pension.
    hired_in_month = bool(data.hire_date and data.period_start < data.hire_date <= data.period_end)
    left_in_month = bool(
        rules.prorate_leavers
        and data.termination_date
        and data.period_start <= data.termination_date < data.period_end
    )
    days_worked = None
    if hired_in_month or left_in_month:
        first = data.hire_date if hired_in_month else data.period_start
        last = data.termination_date if left_in_month else data.period_end
        days_worked = max((last - first).days + 1, 0)

    def earned(amount: Decimal) -> Decimal:
        if days_worked is None:
            return amount
        return min(money(amount * days_worked / rules.absence_divisor), amount)

    basic_earned = earned(basic)
    transport_earned = earned(transport) if rules.prorate_allowances else transport
    other_earned = earned(other) if rules.prorate_allowances else other

    # Transport paid is what is left after leave and absence days are taken off.
    transport_payable = max(money(transport_earned - absence.transport_deduction), money(0))
    gross = money(basic_earned + transport_payable + other_earned + overtime + bonus)

    # Taxable income: basic earned after unpaid absence, plus each other part only where the
    # rules say it is taxable.
    taxable_base = max(
        money(
            basic_earned
            - absence.basic_deduction
            + (overtime if rules.ot_taxable else 0)
            + (transport_payable if rules.transport_taxable else 0)
            + (other_earned if data.other_allowances_taxable else 0)
        ),
        money(0),
    )

    # A taxable bonus is income for the month. Its tax is the increase it causes.
    if rules.bonus_taxable and bonus > 0:
        bonus_result = calculate_bonus_tax(taxable_base, bonus, brackets)
        taxable_income = bonus_result.taxable_with_bonus
        bonus_tax = bonus_result.bonus_tax
    else:
        taxable_income = taxable_base
        bonus_tax = money(0)
    tax = calculate_paye(taxable_income, brackets)

    # Pension: a new hire pays nothing for fewer than pension_min_days of service, otherwise
    # on the pay they earned. Everyone else pays on basic earned after unpaid absence.
    if hired_in_month:
        pensionable = money(0) if days_worked < rules.pension_min_days else basic_earned
    else:
        pensionable = max(money(basic_earned - absence.basic_deduction), money(0))
    pension = calculate_pension(
        pensionable, rules.pension_employee_rate, rules.pension_employer_rate
    )

    total_deductions = money(
        tax.paye + pension.employee_contribution + absence.basic_deduction + advance
    )
    net = money(gross - total_deductions)
    warnings = ("net_salary_is_negative",) if net < 0 else ()

    return Payslip(
        basic_salary=basic,
        basic_earned=basic_earned,
        days_worked=days_worked,
        transport_payable=transport_payable,
        other_allowances=other_earned,
        overtime_pay=overtime,
        bonus=bonus,
        gross_earnings=gross,
        absence=absence,
        taxable_income=taxable_income,
        tax=tax,
        bonus_tax=bonus_tax,
        pensionable_salary=pension.pensionable_salary,
        pension_service_days=days_worked if hired_in_month else None,
        pension_prorated=hired_in_month,
        pension=pension,
        salary_advance=advance,
        total_deductions=total_deductions,
        net_salary=net,
        employer_cost=money(gross + pension.employer_contribution),
        warnings=warnings,
    )
