"""What goes into one employee's pay besides their salary, and how other modules add to it.

The payroll module fills ``EmployeeInputs`` from its own records (approved bonuses and salary
advances), then passes it through the ``payroll.employee_inputs`` hook. The attendance and
overtime modules, or a client extension, register on that hook to add absences and overtime
pay. Import this module before registering, so the hook is declared.

No Django imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from core.extensions.registry import registry

HOOK = "payroll.employee_inputs"

registry.declare(
    HOOK,
    "Adjust one employee's pay inputs before payroll is calculated. Receives an EmployeeInputs "
    "and returns it (changed or not). Keyword arguments: employee, period_start, period_end.",
)


@dataclass
class EmployeeInputs:
    attendance: list = field(default_factory=list)  # DayRecord items: absences, paid leave
    overtime_pay: Decimal = Decimal("0")
    bonus: Decimal = Decimal("0")
    salary_advance: Decimal = Decimal("0")


def gather(inputs: EmployeeInputs, *, employee, period_start: date, period_end: date) -> EmployeeInputs:
    """Pass the inputs through every function registered on the hook."""
    result = registry.pipe(
        HOOK, inputs, employee=employee, period_start=period_start, period_end=period_end
    )
    if not isinstance(result, EmployeeInputs):
        raise TypeError(f"A {HOOK} function must return EmployeeInputs, not {type(result).__name__}")
    return result
