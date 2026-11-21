"""Read and validate a client's ``client.toml``, and load the client's extension package.

Pure Python with no Django imports, so settings can use it before Django is configured.

Rates in the ``[rules]`` section must be written as quoted text (``"0.07"``), never as
TOML floats, so money rules are never subject to binary floating-point error.
"""
from __future__ import annotations

import importlib
import re
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any

KNOWN_MODULES = ("hr", "attendance", "leave", "overtime", "payroll")

# A module can only be enabled when everything it needs is enabled too.
MODULE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "hr": (),
    "attendance": ("hr",),
    "leave": ("hr",),
    "overtime": ("hr",),
    "payroll": ("hr",),
}

# Rule keys a client may override: key -> (kind, low, high). Unknown keys are rejected so
# a typo in client.toml fails loudly instead of being silently ignored.
RULE_KEYS: dict[str, tuple[str, int | None, int | None]] = {
    "absence_divisor": ("int", 1, 31),
    "ot_days": ("int", 1, 31),
    "ot_hours_per_day": ("int", 1, 24),
    "weekly_rest_day": ("int", 0, 6),
    "pension_employee_rate": ("rate", None, None),
    "pension_employer_rate": ("rate", None, None),
    "pension_min_days": ("int", 0, 31),
    "ot_taxable": ("bool", None, None),
    "transport_taxable": ("bool", None, None),
    "bonus_taxable": ("bool", None, None),
}

SECTIONS = {"client", "company", "modules", "country", "rules", "extension"}

_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_COUNTRY = re.compile(r"^[a-z]{2}$")
_PACKAGE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


class ClientConfigError(Exception):
    """The client configuration is missing, malformed or inconsistent."""


@dataclass(frozen=True)
class ClientConfig:
    slug: str
    display_name: str
    company: Mapping[str, str]
    enabled_modules: tuple[str, ...]
    country_pack: str
    rule_overrides: Mapping[str, Any]
    extension_package: str | None
    source_path: Path | None = None

    def has_module(self, name: str) -> bool:
        return name in self.enabled_modules


def _section(raw: Mapping[str, Any], name: str, errors: list[str]) -> Mapping[str, Any]:
    value = raw.get(name, {})
    if not isinstance(value, Mapping):
        errors.append(f"[{name}] must be a table")
        return {}
    return value


def _check_rule(key: str, value: Any, errors: list[str]) -> tuple[bool, Any]:
    """Validate one rule override. Returns (ok, normalised value)."""
    kind, low, high = RULE_KEYS[key]
    if kind == "bool":
        if isinstance(value, bool):
            return True, value
        errors.append(f"[rules] {key} must be true or false")
        return False, None
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"[rules] {key} must be a whole number")
            return False, None
        if value < low or value > high:
            errors.append(f"[rules] {key} must be between {low} and {high}")
            return False, None
        return True, value
    # kind == "rate": a decimal fraction between 0 and 1, written as quoted text.
    if isinstance(value, float):
        errors.append(f'[rules] {key} must be quoted text, for example "0.07", not a number')
        return False, None
    if not isinstance(value, str):
        errors.append(f'[rules] {key} must be quoted text, for example "0.07"')
        return False, None
    try:
        rate = Decimal(value)
    except InvalidOperation:
        errors.append(f"[rules] {key} is not a valid decimal: {value!r}")
        return False, None
    if not rate.is_finite() or rate < 0 or rate > 1:
        errors.append(f"[rules] {key} must be between 0 and 1")
        return False, None
    return True, rate


def parse_client_config(
    raw: Mapping[str, Any], source_path: Path | None = None
) -> ClientConfig:
    """Validate a parsed client.toml. Every problem found is reported together."""
    errors: list[str] = []

    unknown = sorted(set(raw) - SECTIONS)
    if unknown:
        errors.append(f"unknown section(s): {', '.join(unknown)}")

    client = _section(raw, "client", errors)
    slug = client.get("slug")
    if not isinstance(slug, str) or not _SLUG.match(slug):
        errors.append(
            "[client] slug is required: lowercase letters, digits, '-' or '_' (for example 'acme')"
        )
        slug = ""
    display_name = client.get("display_name", slug)
    if not isinstance(display_name, str) or not display_name.strip():
        errors.append("[client] display_name must be text")
        display_name = slug

    company: dict[str, str] = {}
    for key, value in _section(raw, "company", errors).items():
        if isinstance(value, str):
            company[key] = value
        else:
            errors.append(f"[company] {key} must be text")
    if not company.get("legal_name", "").strip():
        errors.append("[company] legal_name is required")

    modules_raw = _section(raw, "modules", errors)
    listed = modules_raw.get("enabled")
    enabled: list[str] = []
    if not isinstance(listed, list) or not listed or not all(isinstance(m, str) for m in listed):
        errors.append("[modules] enabled must be a non-empty list of module names")
    else:
        unknown_modules = [m for m in listed if m not in KNOWN_MODULES]
        if unknown_modules:
            errors.append(
                f"[modules] unknown module(s): {', '.join(unknown_modules)}. "
                f"Known modules: {', '.join(KNOWN_MODULES)}"
            )
        for name in listed:
            if name in KNOWN_MODULES and name not in enabled:
                enabled.append(name)
        for name in enabled:
            for needed in MODULE_DEPENDENCIES[name]:
                if needed not in enabled:
                    errors.append(f"[modules] {name} needs {needed} to be enabled too")

    country_raw = _section(raw, "country", errors)
    country_pack = country_raw.get("pack", "et")
    if not isinstance(country_pack, str) or not _COUNTRY.match(country_pack):
        errors.append("[country] pack must be a two-letter lowercase country code, e.g. 'et'")
        country_pack = "et"

    rules: dict[str, Any] = {}
    for key, value in _section(raw, "rules", errors).items():
        if key not in RULE_KEYS:
            errors.append(f"[rules] unknown rule {key!r}. Known rules: {', '.join(RULE_KEYS)}")
            continue
        ok, normalised = _check_rule(key, value, errors)
        if ok:
            rules[key] = normalised

    package = _section(raw, "extension", errors).get("package")
    if package is not None and (not isinstance(package, str) or not _PACKAGE.match(package)):
        errors.append("[extension] package must be a Python package name, e.g. 'extension_pkg'")
        package = None

    if errors:
        where = f" in {source_path}" if source_path else ""
        raise ClientConfigError(f"Invalid client config{where}:\n  - " + "\n  - ".join(errors))

    return ClientConfig(
        slug=slug,
        display_name=display_name,
        company=MappingProxyType(company),
        enabled_modules=tuple(enabled),
        country_pack=country_pack,
        rule_overrides=MappingProxyType(rules),
        extension_package=package,
        source_path=source_path,
    )


def load_client_config(path: str | Path) -> ClientConfig:
    """Read, parse and validate the ``client.toml`` at ``path``."""
    source = Path(path)
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClientConfigError(f"Client config not found: {source}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ClientConfigError(f"{source} is not valid TOML: {exc}") from exc
    return parse_client_config(raw, source_path=source)


def load_extension(config: ClientConfig, registry: Any) -> bool:
    """Import the client's extension package and call its ``register(registry)``.

    The package is looked up next to ``client.toml`` first. Returns False when the client
    has no extension package, True once it has been loaded.
    """
    name = config.extension_package
    if not name:
        return False
    if config.source_path is not None:
        folder = str(config.source_path.resolve().parent)
        if folder not in sys.path:
            sys.path.append(folder)
    try:
        module = importlib.import_module(name)
    except ImportError as exc:
        raise ClientConfigError(f"Could not import extension package {name!r}: {exc}") from exc
    register = getattr(module, "register", None)
    if not callable(register):
        raise ClientConfigError(f"Extension package {name!r} must define register(registry)")
    register(registry)
    return True
