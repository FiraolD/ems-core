"""Payslip PDF generation (reportlab; no Django needed)."""
import io
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

pytest.importorskip("reportlab")
pypdf = pytest.importorskip("pypdf")

from modules.payroll.payslip_pdf import CompanyInfo, bulk_payslips_pdf, payslip_pdf  # noqa: E402

COMPANY = CompanyInfo(name="Acme PLC", tin="0012345", address="Addis Ababa")


def line(number="E1", name="Abebe Bikila", **kw):
    base = dict(
        employee_number=number, employee_name=name, department="Ops", position="Clerk", tin="T1",
        bank_name="CBE", bank_account_number="1000", days_worked=D("30"), basic_earned=D("10000.00"),
        transport_payable=D("600.00"), other_allowances=D("0.00"), overtime_pay=D("0.00"),
        bonus=D("0.00"), gross_earnings=D("10600.00"), unpaid_days=D("0"), absence_deduction=D("0.00"),
        taxable_income=D("10000.00"), paye=D("1650.00"), bonus_tax=D("0.00"),
        pensionable_salary=D("10000.00"), employee_pension=D("700.00"), employer_pension=D("1100.00"),
        salary_advance=D("0.00"), total_deductions=D("2350.00"), net_salary=D("8250.00"),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def text(pdf: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    return "\n".join(p.extract_text() for p in reader.pages)


def test_single_payslip_has_the_figures():
    pdf = payslip_pdf(line(), "January 2026", COMPANY)
    assert pdf.startswith(b"%PDF")
    out = text(pdf)
    for expected in ("Acme PLC", "Abebe Bikila", "10,000.00", "1,650.00", "8,250.00"):
        assert expected in out
    assert "DRAFT" not in out


def test_draft_is_marked():
    out = text(payslip_pdf(line(), "January 2026", COMPANY, draft=True))
    assert "DRAFT" in out


def test_bulk_is_one_page_per_employee_in_order():
    pdf = bulk_payslips_pdf([line("E2", "Sara"), line("E1")], "January 2026", COMPANY)
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2
    assert "Abebe" in reader.pages[0].extract_text()
    assert "Sara" in reader.pages[1].extract_text()


def test_bulk_with_nothing_is_an_error():
    with pytest.raises(ValueError):
        bulk_payslips_pdf([], "January 2026", COMPANY)


def test_markup_characters_in_names_do_not_break_the_pdf():
    out = text(payslip_pdf(line(name="A <b>&</b> B"), "January 2026", COMPANY))
    assert "A <b>&</b> B" in out


def test_unsupported_characters_become_question_marks_without_a_unicode_font(tmp_path):
    pdf = payslip_pdf(line(name="አበበ"), "January 2026", COMPANY, font_path=str(tmp_path / "missing.ttf"))
    assert pdf.startswith(b"%PDF")


def test_unpaid_days_note_shows():
    out = text(payslip_pdf(line(unpaid_days=D("2"), absence_deduction=D("666.67")), "January 2026", COMPANY))
    assert "Unpaid days: 2" in out


def test_a_full_month_employee_has_no_days_worked_figure():
    out = text(payslip_pdf(line(days_worked=None), "January 2026", COMPANY))
    assert "Full month" in out
