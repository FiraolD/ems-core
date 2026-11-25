import calendar
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

MONEY = {"max_digits": 14, "decimal_places": 2}


class PayrollLocked(Exception):
    """A locked payroll cannot be changed."""


class PayrollPeriod(models.Model):
    """One pay month."""

    year = models.PositiveSmallIntegerField(validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(fields=["year", "month"], name="payroll_one_period_per_month"),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12), name="payroll_month_is_1_to_12"
            ),
        ]

    def __str__(self):
        return self.label

    @property
    def start_date(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def end_date(self) -> date:
        return date(self.year, self.month, calendar.monthrange(self.year, self.month)[1])

    @property
    def label(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"


class PayrollRun(models.Model):
    """The payroll for one month. Draft: can be recalculated. Review: waiting for approval.
    Locked: final; nothing can change it."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        REVIEW = "review", "In review"
        LOCKED = "locked", "Locked"

    period = models.OneToOneField(PayrollPeriod, on_delete=models.PROTECT, related_name="run")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)

    # Everything the figures were calculated with, kept so they can be explained later.
    rules_snapshot = models.JSONField(default=dict, blank=True)
    # Employees who were due pay but could not be calculated, with the reason.
    skipped = models.JSONField(default=list, blank=True)

    calculated_at = models.DateTimeField(null=True, blank=True)
    calculated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # SHA-256 of the figures at the moment of locking; see service.verify_run.
    digest = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-period__year", "-period__month"]
        permissions = [
            ("calculate_payrollrun", "Can calculate, submit and reopen payroll"),
            ("lock_payrollrun", "Can lock payroll (final approval)"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~Q(status="locked") | (Q(locked_at__isnull=False) & ~Q(digest="")),
                name="payroll_locked_run_has_time_and_digest",
            ),
        ]

    def __str__(self):
        return f"Payroll {self.period.label} ({self.get_status_display()})"

    @property
    def is_locked(self) -> bool:
        return self.status == self.Status.LOCKED

    def _locked_in_database(self) -> bool:
        return bool(self.pk) and type(self).objects.filter(pk=self.pk, status=self.Status.LOCKED).exists()

    def save(self, *args, **kwargs):
        if self._locked_in_database():
            raise PayrollLocked(f"{self} is locked and cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.is_locked or self._locked_in_database():
            raise PayrollLocked(f"{self} is locked and cannot be deleted.")
        return super().delete(*args, **kwargs)


class PayrollLineQuerySet(models.QuerySet):
    def _refuse_if_locked(self):
        if self.filter(run__status=PayrollRun.Status.LOCKED).exists():
            raise PayrollLocked("Lines of a locked payroll cannot be changed.")

    def update(self, **kwargs):
        self._refuse_if_locked()
        return super().update(**kwargs)

    def delete(self):
        self._refuse_if_locked()
        return super().delete()


class PayrollLine(models.Model):
    """One employee's pay for the month. A copy of what was calculated: later edits to the
    employee or their salary never change a past line."""

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="payroll_lines")

    # Who they were at the time.
    employee_number = models.CharField(max_length=64)
    employee_name = models.CharField(max_length=200)
    tin = models.CharField(max_length=32, blank=True)
    department = models.CharField(max_length=120, blank=True)
    position = models.CharField(max_length=120, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=64, blank=True)

    # Earnings
    basic_salary = models.DecimalField(**MONEY)
    basic_earned = models.DecimalField(**MONEY)
    days_worked = models.PositiveSmallIntegerField(null=True, blank=True)
    transport_payable = models.DecimalField(**MONEY)
    other_allowances = models.DecimalField(**MONEY)
    overtime_pay = models.DecimalField(**MONEY)
    bonus = models.DecimalField(**MONEY)
    gross_earnings = models.DecimalField(**MONEY)

    # Absence
    unpaid_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))
    paid_leave_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))
    absence_deduction = models.DecimalField(**MONEY)

    # Tax
    taxable_income = models.DecimalField(**MONEY)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4)
    paye = models.DecimalField(**MONEY)
    bonus_tax = models.DecimalField(**MONEY)

    # Pension
    pensionable_salary = models.DecimalField(**MONEY)
    pension_prorated = models.BooleanField(default=False)
    employee_pension = models.DecimalField(**MONEY)
    employer_pension = models.DecimalField(**MONEY)

    # Result
    salary_advance = models.DecimalField(**MONEY)
    total_deductions = models.DecimalField(**MONEY)
    net_salary = models.DecimalField(**MONEY)
    employer_cost = models.DecimalField(**MONEY)
    warnings = models.CharField(max_length=255, blank=True)

    objects = PayrollLineQuerySet.as_manager()

    class Meta:
        ordering = ["employee_number"]
        constraints = [
            models.UniqueConstraint(fields=["run", "employee"], name="payroll_one_line_per_employee"),
        ]

    def __str__(self):
        return f"{self.employee_number} {self.run.period.label}: {self.net_salary}"

    def save(self, *args, **kwargs):
        if self.run.is_locked or PayrollRun.objects.filter(
            pk=self.run_id, status=PayrollRun.Status.LOCKED
        ).exists():
            raise PayrollLocked("Lines of a locked payroll cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if PayrollRun.objects.filter(pk=self.run_id, status=PayrollRun.Status.LOCKED).exists():
            raise PayrollLocked("Lines of a locked payroll cannot be deleted.")
        return super().delete(*args, **kwargs)


class SalaryAdvance(models.Model):
    """Money paid early, deducted from the pay of the month named here."""

    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="advances")
    year = models.PositiveSmallIntegerField(validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "-month", "employee"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payroll_advance_positive"),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12), name="payroll_advance_month_1_to_12"
            ),
        ]

    def __str__(self):
        return f"Advance {self.amount} for {self.employee.employee_number} ({self.year}-{self.month:02d})"


class Bonus(models.Model):
    """A one-off payment in the month named here. Only approved bonuses are paid."""

    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="bonuses")
    year = models.PositiveSmallIntegerField(validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    amount = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0.01"))])
    reason = models.CharField(max_length=255, blank=True)
    approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "-month", "employee"]
        verbose_name_plural = "bonuses"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payroll_bonus_positive"),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12), name="payroll_bonus_month_1_to_12"
            ),
        ]

    def __str__(self):
        return f"Bonus {self.amount} for {self.employee.employee_number} ({self.year}-{self.month:02d})"
