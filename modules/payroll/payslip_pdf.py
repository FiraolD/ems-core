"""Payslip PDFs (one employee, or a whole run in one file).

Built from the figures stored on the payroll line, so a payslip always matches the approved
payroll. No Django imports; the caller passes the company details and optional font path.

Fonts: Amharic names need a font that has Ethiopic glyphs. Set ``EMS_PDF_FONT_PATH`` to a
TrueType file (for example Noto Sans Ethiopic), or install one of the candidates below. With no
suitable font the PDF still builds, and characters the built-in font lacks print as "?" rather
than as blank boxes.
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/noto/NotoSansEthiopic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerifEthiopic-Regular.ttf",
    "C:/Windows/Fonts/nyala.ttf",
    "/Library/Fonts/Nyala.ttf",
    "/usr/share/fonts/truetype/abyssinica/AbyssinicaSIL-R.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
BOLD_CANDIDATES = {
    "NotoSansEthiopic-Regular.ttf": "NotoSansEthiopic-Bold.ttf",
    "DejaVuSans.ttf": "DejaVuSans-Bold.ttf",
}


@dataclass(frozen=True)
class CompanyInfo:
    name: str
    tin: str = ""
    address: str = ""
    currency: str = "ETB"


@dataclass(frozen=True)
class Fonts:
    regular: str
    bold: str
    unicode: bool  # True if a TrueType font was loaded


@lru_cache(maxsize=8)
def load_fonts(font_path: str = "") -> Fonts:
    """Register a TrueType font if one can be found; otherwise use the built-in Helvetica."""
    for path in ([font_path] if font_path else []) + list(FONT_CANDIDATES):
        if path and os.path.isfile(path):
            try:
                base = os.path.basename(path)
                pdfmetrics.registerFont(TTFont("EMS-Regular", path))
                bold_name = BOLD_CANDIDATES.get(base)
                bold_path = os.path.join(os.path.dirname(path), bold_name) if bold_name else ""
                if bold_path and os.path.isfile(bold_path):
                    pdfmetrics.registerFont(TTFont("EMS-Bold", bold_path))
                else:
                    pdfmetrics.registerFont(TTFont("EMS-Bold", path))
                return Fonts("EMS-Regular", "EMS-Bold", True)
            except Exception:  # a broken font file must not stop payslips
                continue
    return Fonts("Helvetica", "Helvetica-Bold", False)


def _text(value, fonts: Fonts) -> str:
    """Escape for the PDF markup; without a Unicode font, replace what Helvetica cannot draw."""
    text = "" if value is None else str(value)
    if not fonts.unicode:
        text = text.encode("latin-1", "replace").decode("latin-1")
    return escape(text)


def _amount(value) -> str:
    return f"{Decimal(value):,.2f}"


def _days(value) -> str:
    """Days as text. Empty means the employee was paid for the whole month."""
    if value is None:
        return "Full month"
    return f"{Decimal(value).normalize():f}"


def _styles(fonts: Fonts):
    base = ParagraphStyle("base", fontName=fonts.regular, fontSize=9, leading=12)
    return {
        "base": base,
        "h1": ParagraphStyle("h1", parent=base, fontName=fonts.bold, fontSize=15, leading=19),
        "muted": ParagraphStyle("muted", parent=base, textColor=colors.HexColor("#5b6472")),
        "label": ParagraphStyle("label", parent=base, fontName=fonts.bold, fontSize=8,
                                textColor=colors.HexColor("#5b6472")),
    }


def deduction_rows(line) -> list[tuple[str, Decimal]]:
    """The deductions listed on a payslip. They add up to ``total_deductions``: income tax (which
    already includes any tax on a bonus), pension, the unpaid-absence deduction and any advance."""
    rows = [
        ("Income tax (PAYE)", line.paye),
        ("Employee pension", line.employee_pension),
        ("Absence (unpaid days)", line.absence_deduction),
        ("Salary advance", line.salary_advance),
    ]
    return [(name, amount) for name, amount in rows if Decimal(amount) != 0 or name.startswith("Income")]


def _slip_story(line, period_label: str, company: CompanyInfo, fonts: Fonts, draft: bool):
    st = _styles(fonts)
    t = lambda v: _text(v, fonts)  # noqa: E731
    cur = t(company.currency)
    story = [
        Paragraph(t(company.name), st["h1"]),
        Paragraph(t(" · ".join(x for x in (f"TIN {company.tin}" if company.tin else "", company.address) if x)),
                  st["muted"]),
        Spacer(1, 5 * mm),
        Paragraph(f"PAYSLIP — {t(period_label)}", st["h1"]),
    ]
    if draft:
        story.append(Paragraph("DRAFT — NOT APPROVED. This payroll has not been locked.",
                               ParagraphStyle("d", parent=st["base"], fontName=fonts.bold,
                                              textColor=colors.HexColor("#b42318"))))
    story.append(Spacer(1, 4 * mm))

    info = [
        [Paragraph("EMPLOYEE", st["label"]), Paragraph(t(line.employee_name), st["base"]),
         Paragraph("EMPLOYEE NO.", st["label"]), Paragraph(t(line.employee_number), st["base"])],
        [Paragraph("DEPARTMENT", st["label"]), Paragraph(t(line.department), st["base"]),
         Paragraph("POSITION", st["label"]), Paragraph(t(line.position), st["base"])],
        [Paragraph("TIN", st["label"]), Paragraph(t(line.tin), st["base"]),
         Paragraph("DAYS PAID", st["label"]), Paragraph(t(_days(line.days_worked)), st["base"])],
    ]
    info_table = Table(info, colWidths=[28 * mm, 62 * mm, 28 * mm, 52 * mm])
    info_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    story += [info_table, Spacer(1, 5 * mm)]

    earnings = [("Basic salary (earned)", line.basic_earned), ("Transport allowance", line.transport_payable),
                ("Other allowances", line.other_allowances), ("Overtime", line.overtime_pay),
                ("Bonus", line.bonus)]
    shown_e = [(n, a) for n, a in earnings if Decimal(a) != 0 or n.startswith("Basic")]
    shown_d = deduction_rows(line)

    rows = [[Paragraph("EARNINGS", st["label"]), Paragraph(f"AMOUNT ({cur})", st["label"]),
             Paragraph("DEDUCTIONS", st["label"]), Paragraph(f"AMOUNT ({cur})", st["label"])]]
    for i in range(max(len(shown_e), len(shown_d))):
        e = shown_e[i] if i < len(shown_e) else ("", None)
        d = shown_d[i] if i < len(shown_d) else ("", None)
        rows.append([e[0], _amount(e[1]) if e[1] is not None else "",
                     d[0], _amount(d[1]) if d[1] is not None else ""])
    rows.append(["Gross earnings", _amount(line.gross_earnings), "Total deductions", _amount(line.total_deductions)])
    table = Table(rows, colWidths=[52 * mm, 33 * mm, 52 * mm, 33 * mm])
    last = len(rows) - 1
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 1), (-1, -1), fonts.regular),
        ("FONTNAME", (0, last), (-1, last), fonts.bold),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#c9d1dc")),
        ("LINEABOVE", (0, last), (-1, last), 0.6, colors.HexColor("#c9d1dc")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3), ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [table, Spacer(1, 4 * mm)]

    net = Table([[Paragraph("NET PAY", ParagraphStyle("n", parent=st["base"], fontName=fonts.bold, fontSize=11)),
                  Paragraph(f"{cur} {_amount(line.net_salary)}",
                            ParagraphStyle("n2", parent=st["base"], fontName=fonts.bold, fontSize=13, alignment=2))]],
                colWidths=[85 * mm, 85 * mm])
    net.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef2f7")),
                             ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9d1dc")),
                             ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [net, Spacer(1, 4 * mm)]

    notes = []
    if Decimal(line.unpaid_days) > 0:
        notes.append(f"Unpaid days: {_days(line.unpaid_days)}.")
    if Decimal(line.bonus_tax) > 0:
        notes.append(f"Income tax includes {_amount(line.bonus_tax)} charged on the bonus.")
    notes.append(f"Taxable income {_amount(line.taxable_income)}; pensionable salary {_amount(line.pensionable_salary)}; "
                 f"employer pension contribution {_amount(line.employer_pension)}.")
    if line.bank_name or line.bank_account_number:
        notes.append(f"Paid to: {line.bank_name} {line.bank_account_number}".strip())
    for note in notes:
        story.append(Paragraph(t(note), st["muted"]))
    return story


def _build(stories: list[list], draft: bool, fonts: Fonts, title: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=18 * mm, title=title, author="EMS")

    def stamp(canvas, _doc):
        if draft:
            canvas.saveState()
            canvas.setFont(fonts.bold, 72)
            canvas.setFillColor(colors.Color(0.7, 0.1, 0.1, alpha=0.12))
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "DRAFT")
            canvas.restoreState()

    flow = []
    for i, story in enumerate(stories):
        if i:
            flow.append(PageBreak())
        flow.extend(story)
    doc.build(flow, onFirstPage=stamp, onLaterPages=stamp)
    return buffer.getvalue()


def payslip_pdf(line, period_label: str, company: CompanyInfo, *, draft: bool = False,
                font_path: str = "") -> bytes:
    fonts = load_fonts(font_path)
    return _build([_slip_story(line, period_label, company, fonts, draft)], draft, fonts,
                  f"Payslip {period_label}")


def bulk_payslips_pdf(lines, period_label: str, company: CompanyInfo, *, draft: bool = False,
                      font_path: str = "") -> bytes:
    """All payslips of a run in one PDF, one per page, in employee-number order."""
    fonts = load_fonts(font_path)
    ordered = sorted(lines, key=lambda ln: ln.employee_number)
    if not ordered:
        raise ValueError("There are no payslips to print.")
    return _build([_slip_story(ln, period_label, company, fonts, draft) for ln in ordered], draft, fonts,
                  f"Payslips {period_label}")
