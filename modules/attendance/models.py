from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from . import logic


class PublicHoliday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} {self.name}"


class AttendanceRecord(models.Model):
    """One employee's attendance for one day. No record means the day counted as worked."""

    class Status(models.TextChoices):
        PRESENT = logic.PRESENT, "Present"
        LATE = logic.LATE, "Late"
        ABSENT = logic.ABSENT, "Absent"
        HALF_DAY = logic.HALF_DAY, "Half day"

    class Source(models.TextChoices):
        MANUAL = "manual", "Entered by hand"
        IMPORT = "import", "CSV import"
        DEVICE = "device", "Attendance device"

    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="attendance_records")
    date = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices)
    note = models.CharField(max_length=logic.MAX_NOTE, blank=True)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.MANUAL)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "employee__employee_number"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="attendance_one_record_per_day")
        ]
        indexes = [models.Index(fields=["date"])]
        permissions = [("import_attendancerecord", "Can import attendance from a file")]

    def __str__(self):
        return f"{self.employee.employee_number} {self.date} {self.status}"

    def clean(self):
        if self.employee_id and self.date and self.date < self.employee.employment_date:
            raise ValidationError({"date": "This is before the employee's start date."})
