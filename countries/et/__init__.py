"""Ethiopia: statutory pay rules (income tax, pension, absence deductions) and the payslip."""
from __future__ import annotations

from .payslip import Payslip, PayslipInput, compute_payslip
from .rules import PayRules, resolve_rules, rules_snapshot
from .tax import Bracket, default_brackets, validate_brackets

CODE = "et"
NAME = "Ethiopia"
CURRENCY = "ETB"

__all__ = [
    "CODE",
    "CURRENCY",
    "NAME",
    "Bracket",
    "PayRules",
    "Payslip",
    "PayslipInput",
    "compute_payslip",
    "default_brackets",
    "resolve_rules",
    "rules_snapshot",
    "validate_brackets",
]
