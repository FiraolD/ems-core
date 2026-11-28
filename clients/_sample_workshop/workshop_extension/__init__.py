"""Sample client extension: a full-attendance bonus.

Everyone employed for the whole month, with no unpaid absence (absent, half day or unpaid leave),
gets a flat bonus. Paid approved leave does not count against them. The amount comes from
``[extension.settings] full_attendance_bonus`` in client.toml, so changing it never needs code.

This runs inside the normal payroll workflow: the bonus is part of the calculated run, so it is
reviewed, locked and audited like any other figure. Core is not edited for this client.
"""
from decimal import Decimal, InvalidOperation

HOOK = "payroll.employee_inputs"
ORDER = 400  # after attendance (100), leave (200) and overtime (300) have added their inputs
UNPAID_STATUSES = frozenset({"absent", "half_day", "unpaid_leave"})


def parse_amount(value) -> Decimal:
    from core.extensions.client import ClientConfigError

    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ClientConfigError(f"full_attendance_bonus must be an amount like '500.00', got {value!r}") from None
    if not amount.is_finite() or amount < 0:
        raise ClientConfigError(f"full_attendance_bonus must be zero or more, got {value!r}")
    return amount


def make_hook(amount: Decimal):
    def add_full_attendance_bonus(inputs, *, employee, period_start, period_end):
        if amount <= 0:
            return inputs
        if employee.employment_date > period_start:
            return inputs  # joined during the month
        if employee.termination_date and employee.termination_date <= period_end:
            return inputs  # left during the month
        if any(record.status in UNPAID_STATUSES for record in inputs.attendance):
            return inputs
        inputs.bonus += amount
        return inputs

    return add_full_attendance_bonus


def _configured_amount() -> Decimal:
    from django.conf import settings

    return parse_amount(settings.EMS_CLIENT.extension_settings.get("full_attendance_bonus", "0"))


def register(registry):
    # Importing the payroll inputs declares the hook; it is only needed when payroll is enabled.
    from django.conf import settings

    if not settings.EMS_CLIENT.has_module("payroll"):
        return
    from modules.payroll import inputs  # noqa: F401  (declares payroll.employee_inputs)

    registry.register(HOOK, make_hook(_configured_amount()), order=ORDER)
