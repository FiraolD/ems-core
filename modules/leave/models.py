from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

DAYS = {"max_digits": 5, "decimal_places": 1}


class LeaveType(models.Model):
    """A kind of leave and how it is paid and counted.

    ``pay_code`` is how payroll treats the days: the paid codes keep full basic salary (the
    transport allowance is reduced as the country pack decides) and ``unpaid_leave`` deducts.
    """

    class PayCode(models.TextChoices):
        ANNUAL = "annual_leave", "Annual leave (paid)"
        SICK = "sick_leave", "Sick leave (paid)"
        MATERNITY = "maternity_leave", "Maternity leave (paid)"
        PATERNITY = "paternity_leave", "Paternity leave (paid)"
        SPECIAL = "special_leave", "Special leave (paid)"
        OTHER = "other_approved_leave", "Other approved leave (paid)"
        UNPAID = "unpaid_leave", "Unpaid leave"

    name = models.CharField(max_length=80, unique=True)
    pay_code = models.CharField(max_length=24, choices=PayCode.choices)
    uses_balance = models.BooleanField(
        default=False, help_text="Tick if there is a yearly allowance that runs out (annual leave)."
    )
    annual_days = models.DecimalField(**DAYS, default=0, validators=[MinValueValidator(0)])
    extra_day_every_years = models.PositiveSmallIntegerField(
        default=0, help_text="One extra day for every this many completed years of service. 0 turns it off."
    )
    carry_over_max = models.DecimalField(
        **DAYS, default=0, validators=[MinValueValidator(0)], help_text="Most unused days carried into next year."
    )
    prorate_first_year = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=Q(annual_days__gte=0), name="leave_type_annual_days_non_negative"),
        ]

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="requests")
    start_date = models.DateField()
    end_date = models.DateField()
    half_day = models.BooleanField(default=False)
    days = models.DecimalField(**DAYS)
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
        ordering = ["-start_date", "employee__employee_number"]
        permissions = [("approve_leaverequest", "Can approve or reject leave requests")]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="leave_end_not_before_start"),
            models.CheckConstraint(condition=Q(days__gt=0), name="leave_days_positive"),
        ]
        indexes = [models.Index(fields=["start_date", "end_date"])]

    def __str__(self):
        return f"{self.employee.employee_number} {self.leave_type} {self.start_date}..{self.end_date}"


class LeaveAdjustment(models.Model):
    """HR correction to someone's balance (opening balance, a granted extra day...). Negative
    values take days away. Kept as a record so every balance can be explained."""

    employee = models.ForeignKey("hr.Employee", on_delete=models.PROTECT, related_name="leave_adjustments")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="adjustments")
    year = models.PositiveSmallIntegerField()
    days = models.DecimalField(**DAYS)
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-year", "employee__employee_number"]

    def __str__(self):
        return f"{self.employee.employee_number} {self.leave_type} {self.year}: {self.days:+}"
