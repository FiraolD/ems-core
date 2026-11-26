"""Adds approved overtime to payroll as money, from the basic salary that applies to the month."""
from __future__ import annotations

from core.rules.service import rules_for

from . import logic, service

ORDER = 300


def add_overtime(inputs, *, employee, period_start, period_end):
    entries = service.approved_entries(employee, period_start, period_end)
    if not entries:
        return inputs
    salary = employee.salary_for_period(period_start, period_end)
    if salary is None:
        return inputs  # payroll lists this employee as skipped; there is nothing to base pay on
    rules = rules_for(period_end).rules
    inputs.overtime_pay += logic.overtime_pay(salary.basic_salary, entries, rules.ot_days, rules.ot_hours_per_day)
    return inputs


def register() -> None:
    from core.extensions.registry import registry
    from modules.payroll import inputs

    registry.register_once(inputs.HOOK, add_overtime, order=ORDER)
