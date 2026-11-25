from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

from . import rules

MONEY = {"max_digits": 14, "decimal_places": 2}


class Department(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=32, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.code = self.code or None  # several blank codes must not collide on uniqueness
        super().save(*args, **kwargs)


class Branch(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=32, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "branches"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.code = self.code or None
        super().save(*args, **kwargs)


class Position(models.Model):
    title = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class Employee(models.Model):
    class Gender(models.TextChoices):
        MALE = "male", "Male"
        FEMALE = "female", "Female"

    class EmploymentType(models.TextChoices):
        PERMANENT = "permanent", "Permanent"
        CONTRACT = "contract", "Contract"
        PROBATION = "probation", "Probation"
        TEMPORARY = "temporary", "Temporary"

    class Status(models.TextChoices):
        ACTIVE = rules.ACTIVE, "Active"
        ON_LEAVE = rules.ON_LEAVE, "On leave"
        SUSPENDED = rules.SUSPENDED, "Suspended"
        RESIGNED = rules.RESIGNED, "Resigned"
        TERMINATED = rules.TERMINATED, "Terminated"
        RETIRED = rules.RETIRED, "Retired"

    employee_number = models.CharField(max_length=64, unique=True)
    full_name = models.CharField(max_length=200, db_index=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    tin = models.CharField("TIN", max_length=32, blank=True)

    department = models.ForeignKey(
        Department, null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )
    position = models.ForeignKey(
        Position, null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )
    branch = models.ForeignKey(
        Branch, null=True, blank=True, on_delete=models.PROTECT, related_name="employees"
    )

    employment_date = models.DateField()
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices, default=EmploymentType.PERMANENT
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )
    termination_date = models.DateField(null=True, blank=True)
    termination_reason = models.CharField(max_length=255, blank=True)

    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=64, blank=True)
    remarks = models.TextField(blank=True)

    # Lets a person sign in and see their own record and payslips (employee self-service).
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="employee",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(termination_date__isnull=True)
                | Q(termination_date__gte=F("employment_date")),
                name="hr_employee_terminated_after_hired",
            ),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.employee_number})"

    def clean(self):
        errors = {}
        if self.employee_number:
            self.employee_number = self.employee_number.strip()
        if self.status in rules.LEFT_STATUSES and not self.termination_date:
            errors["termination_date"] = "Enter the date this employee left."
        if self.termination_date and self.employment_date and (
            self.termination_date < self.employment_date
        ):
            errors["termination_date"] = "The leaving date is before the hiring date."
        if self.date_of_birth and self.employment_date and (
            self.date_of_birth >= self.employment_date
        ):
            errors["date_of_birth"] = "Date of birth must be before the hiring date."
        if errors:
            raise ValidationError(errors)

    @property
    def is_working(self) -> bool:
        return self.status in rules.WORKING_STATUSES

    def eligible_for_period(self, period_start: date, period_end: date) -> bool:
        return rules.eligible_for_period(
            self.employment_date, self.status, self.termination_date, period_start, period_end
        )

    def salary_on(self, as_of: date) -> "SalaryRecord | None":
        """The salary in force on ``as_of``, or None if none has started yet."""
        return (
            self.salary_records.filter(effective_date__lte=as_of)
            .order_by("-effective_date", "-id")
            .first()
        )

    def salary_for_period(self, period_start: date, period_end: date) -> "SalaryRecord | None":
        """The salary that pays for a month. A raise applies from the next month."""
        return rules.salary_for_period(self.salary_records.all(), period_start, period_end)

    @property
    def current_salary(self) -> "SalaryRecord | None":
        return self.salary_on(date.today())


class SalaryRecord(models.Model):
    """One salary decision, effective from a date. The full history is kept.

    The record in force on a date is the latest one effective on or before it, so a raise
    can be entered ahead of time and a past correction is applied to the right months.
    """

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="salary_records")
    effective_date = models.DateField(db_index=True)
    basic_salary = models.DecimalField(**MONEY, validators=[MinValueValidator(Decimal("0"))])
    transport_allowance = models.DecimalField(
        **MONEY, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))]
    )
    other_allowances = models.DecimalField(
        **MONEY, default=Decimal("0.00"), validators=[MinValueValidator(Decimal("0"))]
    )
    other_allowances_taxable = models.BooleanField(default=True)
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_date", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "effective_date"], name="hr_one_salary_per_employee_date"
            ),
            models.CheckConstraint(
                condition=Q(basic_salary__gte=0)
                & Q(transport_allowance__gte=0)
                & Q(other_allowances__gte=0),
                name="hr_salary_not_negative",
            ),
        ]

    def __str__(self):
        return f"{self.employee.employee_number} from {self.effective_date}: {self.basic_salary}"

    @property
    def gross(self) -> Decimal:
        return self.basic_salary + self.transport_allowance + self.other_allowances
