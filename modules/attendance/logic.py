"""Attendance rules and CSV import parsing.

A day with no record counts as worked. Only recorded absences and half days reduce pay, so an
unrecorded day never costs an employee money by accident (reports list the gaps instead).

No Django imports.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

PRESENT = "present"
LATE = "late"
ABSENT = "absent"
HALF_DAY = "half_day"
STATUSES = (PRESENT, LATE, ABSENT, HALF_DAY)

# Statuses that reduce pay, as the country packs name them (see countries/et/absence.py).
PAY_AFFECTING = {ABSENT: "absent", HALF_DAY: "half_day"}

MAX_ROWS = 20000
MAX_NOTE = 200
REQUIRED_COLUMNS = ("employee_number", "date", "status")


def pay_statuses(records: Iterable[tuple[date, str]]) -> list[tuple[date, str]]:
    """(day, pack status) for each record that affects pay; present and late days do not."""
    return [(day, PAY_AFFECTING[status]) for day, status in records if status in PAY_AFFECTING]


@dataclass(frozen=True)
class ImportRow:
    employee_number: str
    day: date
    status: str
    note: str = ""


@dataclass
class ImportResult:
    rows: list[ImportRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and bool(self.rows)


def parse_import(text: str, known_numbers: set[str], *, today: date | None = None) -> ImportResult:
    """Read a CSV of employee_number,date,status[,note].

    All or nothing: if any row has a problem the result has errors and callers import nothing,
    so a half-loaded month can never be mistaken for a complete one. Dates are YYYY-MM-DD.
    """
    result = ImportResult()
    text = text.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        result.errors.append("The file is empty.")
        return result
    headers = [h.strip().lower() for h in reader.fieldnames if h is not None]
    reader.fieldnames = [h.strip().lower() if h is not None else h for h in reader.fieldnames]
    missing = [c for c in REQUIRED_COLUMNS if c not in headers]
    if missing:
        result.errors.append(f"Missing column(s): {', '.join(missing)}. Expected: employee_number, date, status, note.")
        return result

    seen: set[tuple[str, date]] = set()
    for count, row in enumerate(reader, start=1):
        line = count + 1  # the header is line 1
        if count > MAX_ROWS:
            result.errors.append(f"Too many rows: the limit is {MAX_ROWS} per file.")
            break
        if None in row:
            result.errors.append(f"Line {line}: too many columns.")
            continue
        number = (row.get("employee_number") or "").strip()
        raw_day = (row.get("date") or "").strip()
        status = (row.get("status") or "").strip().lower()
        note = (row.get("note") or "").strip()
        if not (number or raw_day or status):
            continue  # blank line
        problems = []
        if number not in known_numbers:
            problems.append(f"unknown employee number {number!r}")
        day = None
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            problems.append(f"date {raw_day!r} is not YYYY-MM-DD")
        if day and today and day > today:
            problems.append(f"date {raw_day} is in the future")
        if status not in STATUSES:
            problems.append(f"status {status!r} must be one of: {', '.join(STATUSES)}")
        if len(note) > MAX_NOTE:
            problems.append(f"note is longer than {MAX_NOTE} characters")
        if day and number and (number, day) in seen:
            problems.append(f"{number} is listed twice for {raw_day}")
        if problems:
            result.errors.append(f"Line {line}: " + "; ".join(problems) + ".")
            continue
        seen.add((number, day))
        result.rows.append(ImportRow(number, day, status, note))

    if not result.errors and not result.rows:
        result.errors.append("The file has no attendance rows.")
    return result


SUMMARY_HEADERS = ("Employee No.", "Name", "Present", "Late", "Absent", "Half day")  # same order as STATUSES


def monthly_summary(people: Iterable[tuple[str, str]], records: Iterable[tuple[str, str]]):
    """Counts of each recorded status per employee for a month.

    ``people`` are (employee_number, name) for everyone who should appear (so employees with no
    records show zeros); ``records`` are (employee_number, status). Returns (rows, totals).
    Only recorded days are counted: days nobody recorded are not shown as present.
    """
    counts = {number: dict.fromkeys(STATUSES, 0) for number, _ in people}
    for number, status in records:
        if number in counts and status in counts[number]:
            counts[number][status] += 1
    rows = [
        (number, name, *(counts[number][s] for s in STATUSES)) for number, name in sorted(people)
    ]
    totals = ("TOTAL", f"{len(rows)} employees", *(sum(r[i] for r in rows) for i in range(2, 2 + len(STATUSES))))
    return rows, totals
