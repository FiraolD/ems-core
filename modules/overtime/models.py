from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from . import logic


class OvertimeCategory(models.Model):
    """How much each kind of overtime pays: a multiple of the ordinary hourly rate."""

    kind = models.CharField(
        max_length=16,
        unique=True,
        choices=[
            (logic.NORMAL, "Ordinary day"),
            (logic.NIGHT, "Night"),
            (logic.REST_DAY, "Weekly rest day"),
            (logic.HOLIDAY, "Public holiday"),
        ],
    )
    multiplier = models.DecimalField(max_digits=4, decimal_places=2, validators=[MinValueValidator(1)])
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "overtime categories"
        ordering = ["multiplier"]
        constraints = [models.CheckConstraint(condition=Q(multiplier__gte=1), name="overtime_multiplier_at_least_1")]

    def __str__(self):
        return f"{self.get_kind_display()} x{self.multiplier}"


class OvertimeEntry(models.Model):
    """Hours worked on one day. The multiplier is copied in when the entry is made, so changing
    a category's rate later never changes overtime already recorded."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="overtime_entries")
    work_date = models.DateField()
    hours = models.DecimalField(max_digits=4, decimal_places=2)
    category = models.ForeignKey(OvertimeCategory, on_delete=models.PROTECT, related_name="entries")
    multiplier = models.DecimalField(max_digits=4, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "overtime entries"
        ordering = ["-work_date", "employee__employee_number"]
        permissions = [("approve_overtimeentry", "Can approve or reject overtime")]
        constraints = [
            models.CheckConstraint(condition=Q(hours__gt=0), name="overtime_hours_positive"),
            models.CheckConstraint(condition=Q(multiplier__gte=1), name="overtime_entry_multiplier_at_least_1"),
        ]
        indexes = [models.Index(fields=["work_date"])]

    def __str__(self):
        return f"{self.employee.employee_number} {self.work_date} {self.hours}h"
