"""The pay rules and tax schedule in force on a date. Payroll calls this once per run.

Precedence: value set in the system, then the client's client.toml ``[rules]``, then the
country pack's default.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.conf import settings

from countries import get_pack

from .models import RuleValue, TaxSchedule
from .resolve import RuleEntry, effective_overrides


def _pack():
    return get_pack(settings.EMS_CLIENT.country_pack)


@dataclass(frozen=True)
class RulesInForce:
    as_of: date
    rules: Any  # the country pack's PayRules
    brackets: tuple
    snapshot: dict  # plain data to store with a payroll run


def pay_rules_for(as_of: date):
    pack = _pack()
    entries = [
        RuleEntry(row.key, row.typed_value, row.effective_from)
        for row in RuleValue.objects.filter(effective_from__lte=as_of)
    ]
    merged = effective_overrides(settings.EMS_CLIENT.rule_overrides, entries, as_of)
    return pack.resolve_rules(merged)


def tax_brackets_for(as_of: date) -> tuple:
    """The schedule in force, checked for gaps and breaks. A broken schedule is an error,
    never a silent fallback, because tax would otherwise be wrong without anyone noticing."""
    pack = _pack()
    schedule = (
        TaxSchedule.objects.filter(effective_from__lte=as_of)
        .order_by("-effective_from")
        .prefetch_related("bands")
        .first()
    )
    if schedule is None:
        brackets = tuple(pack.default_brackets())
    else:
        brackets = tuple(
            pack.Bracket(band.min_income, band.max_income, band.rate, band.quick_deduction)
            for band in schedule.bands.all()
        )
    pack.validate_brackets(brackets)
    return brackets


def rules_for(as_of: date) -> RulesInForce:
    pack = _pack()
    rules = pay_rules_for(as_of)
    brackets = tax_brackets_for(as_of)
    return RulesInForce(as_of, rules, brackets, pack.rules_snapshot(rules, brackets))
