"""Payroll reports as plain rows, and a safe CSV writer.

Reports read the figures stored on each payroll line (never recalculating), so a report always
agrees with the payslips and with what was approved.

No Django imports: lines are anything with the PayrollLine attribute names.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from core.money import money

BOM = "﻿"  # lets Excel open the file as UTF-8, so Amharic names display correctly
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple, ...]
    totals: tuple  # same width as headers; "" where a total makes no sense


def safe_cell(value) -> str:
    """Text for one CSV cell. Text that a spreadsheet would run as a formula is neutralised."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    text = str(value)
    if text.startswith(_FORMULA_STARTS):
        return "'" + text
    return text


def to_csv(report: Report) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([safe_cell(h) for h in report.headers])
    for row in report.rows:
        writer.writerow([safe_cell(c) for c in row])
    writer.writerow([safe_cell(c) for c in report.totals])
    return BOM + out.getvalue()


def _sum(lines: Sequence, attr: str) -> Decimal:
    return money(sum((Decimal(getattr(line, attr)) for line in lines), Decimal("0")))


def _ordered(lines: Iterable) -> list:
    return sorted(lines, key=lambda line: line.employee_number)


def register(lines: Iterable) -> Report:
    rows_in = _ordered(lines)
    headers = ("Employee No.", "Name", "Department", "Basic earned", "Transport", "Other allowances",
               "Overtime", "Bonus", "Gross", "Absence", "Income tax", "Of which on bonus", "Pension (employee)",
               "Advance", "Total deductions", "Net pay")
    # Absence is shown for information: it is already out of basic earned, not a further deduction.
    order = ("basic_earned", "transport_payable", "other_allowances", "overtime_pay", "bonus",
             "gross_earnings", "absence_deduction", "paye", "bonus_tax", "employee_pension",
             "salary_advance", "total_deductions", "net_salary")
    rows = tuple(
        (ln.employee_number, ln.employee_name, ln.department, *(getattr(ln, c) for c in order))
        for ln in rows_in
    )
    totals = ("TOTAL", f"{len(rows_in)} employees", "", *(_sum(rows_in, c) for c in order))
    return Report("register", "Payroll register", headers, rows, totals)


def income_tax(lines: Iterable) -> Report:
    rows_in = _ordered(lines)
    # Income tax (PAYE) is charged on taxable income that already includes any bonus, so the
    # tax on a bonus is part of it, never added on top. It is shown for information only.
    headers = ("Employee No.", "Name", "TIN", "Taxable income", "Rate", "Income tax (PAYE)", "Of which on bonus")
    rows = tuple(
        (ln.employee_number, ln.employee_name, ln.tin, ln.taxable_income, ln.tax_rate, ln.paye, ln.bonus_tax)
        for ln in rows_in
    )
    totals = ("TOTAL", f"{len(rows_in)} employees", "", _sum(rows_in, "taxable_income"), "",
              _sum(rows_in, "paye"), _sum(rows_in, "bonus_tax"))
    return Report("income-tax", "Income tax", headers, rows, totals)


def pension(lines: Iterable) -> Report:
    rows_in = _ordered(lines)
    headers = ("Employee No.", "Name", "TIN", "Pensionable salary", "Employee", "Employer", "Total")
    rows = tuple(
        (ln.employee_number, ln.employee_name, ln.tin, ln.pensionable_salary, ln.employee_pension,
         ln.employer_pension, money(Decimal(ln.employee_pension) + Decimal(ln.employer_pension)))
        for ln in rows_in
    )
    ee, er = _sum(rows_in, "employee_pension"), _sum(rows_in, "employer_pension")
    totals = ("TOTAL", f"{len(rows_in)} employees", "", _sum(rows_in, "pensionable_salary"), ee, er, money(ee + er))
    return Report("pension", "Pension contributions", headers, rows, totals)


def bank_transfer(lines: Iterable) -> Report:
    """Who to pay and how much. Employees with no bank account are listed with a blank, not hidden."""
    rows_in = [ln for ln in _ordered(lines) if Decimal(ln.net_salary) > 0]
    headers = ("Employee No.", "Name", "Bank", "Account number", "Net pay")
    rows = tuple(
        (ln.employee_number, ln.employee_name, ln.bank_name, ln.bank_account_number, ln.net_salary)
        for ln in rows_in
    )
    totals = ("TOTAL", f"{len(rows_in)} employees", "", "", _sum(rows_in, "net_salary"))
    return Report("bank-transfer", "Bank transfer list", headers, rows, totals)


REPORTS = {
    "register": register,
    "income-tax": income_tax,
    "pension": pension,
    "bank-transfer": bank_transfer,
}


def missing_bank_details(lines: Iterable) -> list[str]:
    """Employee numbers who are owed pay but have no bank name or account number."""
    return [
        ln.employee_number
        for ln in _ordered(lines)
        if Decimal(ln.net_salary) > 0 and not (ln.bank_name and ln.bank_account_number)
    ]
