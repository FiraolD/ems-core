"""Attendance import: all or nothing, audited."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.audit.service import record
from modules.hr.models import Employee

from . import logic
from .models import AttendanceRecord

IMPORT = "attendance.import_attendancerecord"


class ImportRejected(Exception):
    """The file has problems. ``errors`` lists them; nothing was imported."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:3]))
        self.errors = errors


@dataclass(frozen=True)
class ImportSummary:
    created: int
    updated: int
    unchanged: int


def import_csv(text: str, user, *, today: date | None = None) -> ImportSummary:
    if user is None or not user.has_perm(IMPORT):
        raise PermissionDenied(f"You do not have permission: {IMPORT}")
    employees = {e.employee_number: e for e in Employee.objects.all()}
    parsed = logic.parse_import(text, set(employees), today=today)
    errors = list(parsed.errors)
    # Days before an employee started are rejected here, with the other row problems.
    for row in parsed.rows:
        if row.day < employees[row.employee_number].employment_date:
            errors.append(f"{row.employee_number} {row.day}: before the employee's start date.")
    if errors:
        raise ImportRejected(errors)

    created = updated = unchanged = 0
    with transaction.atomic():
        for row in parsed.rows:
            existing = AttendanceRecord.objects.filter(
                employee=employees[row.employee_number], date=row.day
            ).first()
            if existing is None:
                AttendanceRecord.objects.create(
                    employee=employees[row.employee_number], date=row.day, status=row.status,
                    note=row.note, source=AttendanceRecord.Source.IMPORT, recorded_by=user,
                )
                created += 1
            elif (existing.status, existing.note) == (row.status, row.note):
                unchanged += 1
            else:
                existing.status, existing.note = row.status, row.note
                existing.source = AttendanceRecord.Source.IMPORT
                existing.recorded_by = user
                existing.save()
                updated += 1
        record(
            "attendance.imported",
            actor=user,
            object_type="attendance.attendancerecord",
            object_repr="CSV import",
            changes={"created": created, "updated": updated, "unchanged": unchanged},
        )
    return ImportSummary(created, updated, unchanged)
