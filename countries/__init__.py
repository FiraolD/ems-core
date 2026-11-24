"""Statutory packs, one per country. A client's ``[country] pack`` picks which one is used.

A pack is a package ``countries.<code>`` exposing ``CODE``, ``NAME``, ``CURRENCY``,
``Bracket``, ``default_brackets``, ``validate_brackets``, ``resolve_rules``,
``rules_snapshot`` and ``compute_payslip``.
"""
from __future__ import annotations

import importlib
from types import ModuleType


class UnknownCountryPack(LookupError):
    """The client names a country pack that is not installed."""


def get_pack(code: str) -> ModuleType:
    if not code.isalpha() or not code.islower() or len(code) != 2:
        raise UnknownCountryPack(f"Invalid country pack code: {code!r}")
    try:
        return importlib.import_module(f"countries.{code}")
    except ModuleNotFoundError as exc:
        if exc.name == f"countries.{code}":
            raise UnknownCountryPack(f"There is no country pack {code!r}") from exc
        raise
