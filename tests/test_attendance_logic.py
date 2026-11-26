"""Attendance CSV parsing and pay mapping (no Django needed)."""
from datetime import date

from modules.attendance import logic

KNOWN = {"E1", "E2"}
HEADER = "employee_number,date,status,note\n"


def parse(body, **kw):
    return logic.parse_import(HEADER + body, KNOWN, **kw)


def test_a_clean_file_is_read():
    r = parse("E1,2026-09-03,absent,sick\nE2,2026-09-04,Half_Day,\n")
    assert r.ok and not r.errors
    assert [(x.employee_number, x.day, x.status, x.note) for x in r.rows] == [
        ("E1", date(2026, 9, 3), "absent", "sick"),
        ("E2", date(2026, 9, 4), "half_day", ""),
    ]


def test_bom_and_header_case_and_blank_lines_are_tolerated():
    text = "﻿Employee_Number, Date ,STATUS\nE1,2026-09-03,present\n,,\n"
    r = logic.parse_import(text, KNOWN)
    assert r.ok and len(r.rows) == 1


def test_any_bad_row_rejects_everything_and_names_the_line():
    r = parse("E1,2026-09-03,absent,\nZZ,2026-09-03,absent,\nE2,03/09/2026,absent,\nE2,2026-09-05,holiday,\n")
    assert not r.ok
    assert len(r.errors) == 3
    assert r.errors[0].startswith("Line 3") and "unknown employee" in r.errors[0]
    assert r.errors[1].startswith("Line 4") and "YYYY-MM-DD" in r.errors[1]
    assert r.errors[2].startswith("Line 5") and "status" in r.errors[2]


def test_duplicate_employee_day_is_rejected():
    r = parse("E1,2026-09-03,absent,\nE1,2026-09-03,present,\n")
    assert any("twice" in e for e in r.errors)


def test_future_dates_are_rejected_when_today_is_given():
    r = parse("E1,2026-09-30,absent,\n", today=date(2026, 9, 15))
    assert any("future" in e for e in r.errors)


def test_missing_column_empty_and_header_only_files():
    assert "Missing column" in logic.parse_import("employee_number,date\nE1,2026-09-03\n", KNOWN).errors[0]
    assert logic.parse_import("", KNOWN).errors == ["The file is empty."]
    assert "no attendance rows" in parse("").errors[0]


def test_too_many_columns_and_long_notes_are_rejected():
    assert any("too many columns" in e for e in parse("E1,2026-09-03,absent,x,y\n").errors)
    assert any("note is longer" in e for e in parse(f"E1,2026-09-03,absent,{'x' * 201}\n").errors)


def test_row_limit(monkeypatch):
    monkeypatch.setattr(logic, "MAX_ROWS", 2)
    r = parse("E1,2026-09-01,absent,\nE1,2026-09-02,absent,\nE1,2026-09-03,absent,\n")
    assert any("Too many rows" in e for e in r.errors)


def test_only_absences_and_half_days_affect_pay():
    d = date(2026, 9, 1)
    out = logic.pay_statuses([(d, "present"), (d, "late"), (d, "absent"), (d, "half_day")])
    assert out == [(d, "absent"), (d, "half_day")]
