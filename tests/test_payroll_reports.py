"""Payroll reports and CSV export (no Django needed)."""
from decimal import Decimal as D
from types import SimpleNamespace

from modules.payroll import reports


def line(number="E1", name="Abebe", **kw):
    base = dict(
        employee_number=number, employee_name=name, department="Ops", tin="T1",
        bank_name="CBE", bank_account_number="1000", basic_earned=D("10000.00"),
        transport_payable=D("600.00"), other_allowances=D("0.00"), overtime_pay=D("0.00"),
        bonus=D("0.00"), gross_earnings=D("10600.00"), absence_deduction=D("0.00"),
        taxable_income=D("10000.00"), tax_rate=D("0.30"), paye=D("1650.00"), bonus_tax=D("0.00"),
        pensionable_salary=D("10000.00"), employee_pension=D("700.00"), employer_pension=D("1100.00"),
        salary_advance=D("0.00"), total_deductions=D("2350.00"), net_salary=D("8250.00"),
    )
    base.update(kw)
    return SimpleNamespace(**base)


LINES = [line("E2", "Sara", net_salary=D("5000.00"), paye=D("500.00"), employee_pension=D("350.00"),
              employer_pension=D("550.00"), gross_earnings=D("5000.00"), bank_name="", bank_account_number=""),
         line("E1")]


def test_register_is_sorted_and_totals_add_up():
    r = reports.register(LINES)
    assert [row[0] for row in r.rows] == ["E1", "E2"]
    assert r.totals[0] == "TOTAL"
    assert r.totals[-1] == D("13250.00")  # net 8250 + 5000


def test_income_tax_report_does_not_count_bonus_tax_twice():
    # PAYE is charged on income that includes the bonus, so bonus tax is part of it.
    r = reports.income_tax([line(paye=D("1750.00"), bonus_tax=D("100.00"))])
    assert r.headers[-2:] == ("Income tax (PAYE)", "Of which on bonus")
    assert r.rows[0][-2:] == (D("1750.00"), D("100.00"))
    assert r.totals[-2:] == (D("1750.00"), D("100.00"))  # the tax total is PAYE alone


def test_pension_totals_employee_employer_and_both():
    r = reports.pension(LINES)
    assert r.totals[4] == D("1050.00")
    assert r.totals[5] == D("1650.00")
    assert r.totals[6] == D("2700.00")


def test_bank_transfer_skips_zero_net_and_flags_missing_details():
    zero = line("E3", net_salary=D("0.00"))
    r = reports.bank_transfer([*LINES, zero])
    assert [row[0] for row in r.rows] == ["E1", "E2"]
    assert reports.missing_bank_details([*LINES, zero]) == ["E2"]


def test_csv_has_bom_header_and_total_row():
    text = reports.to_csv(reports.bank_transfer(LINES))
    assert text.startswith(reports.BOM)
    lines = text.lstrip(reports.BOM).split("\r\n")
    assert lines[0].startswith("Employee No.")
    assert lines[-2].startswith("TOTAL")


def test_csv_neutralises_formulas():
    r = reports.bank_transfer([line(employee_name="=HYPERLINK(\"http://x\")")])
    text = reports.to_csv(r)
    assert "'=HYPERLINK" in text
    assert ",=HYPERLINK" not in text


def test_safe_cell_variants():
    assert reports.safe_cell(None) == ""
    assert reports.safe_cell(D("5")) == "5.00"
    for bad in ("+1", "-1", "@a", "=1"):
        assert reports.safe_cell(bad).startswith("'")
    assert reports.safe_cell("አበበ") == "አበበ"


def test_empty_run_gives_zero_totals():
    r = reports.register([])
    assert r.rows == ()
    assert r.totals[-1] == D("0.00")
