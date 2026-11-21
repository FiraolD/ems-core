"""Work out what changed between two versions of a record, safe to store as JSON.

No Django imports. Values that must never be written to the log (passwords, tokens) are
replaced by ``REDACTED``; the field still appears, so the log shows that it changed.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

REDACTED = "[redacted]"
_SENSITIVE_PARTS = ("password", "secret", "token", "api_key", "apikey")


def is_sensitive(field_name: str) -> bool:
    lowered = field_name.lower()
    return any(part in lowered for part in _SENSITIVE_PARTS)


def jsonable(value: Any) -> Any:
    """Convert a field value to something ``json.dumps`` accepts, without losing precision."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal | UUID):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return "[binary]"
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((jsonable(v) for v in value), key=str)
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    return str(value)


def diff_values(
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
    *,
    exclude: Iterable[str] = (),
    redact: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """Fields that differ, as ``{field: {"old": ..., "new": ...}}``.

    ``before=None`` describes a new record and ``after=None`` a deleted one. Fields in
    ``exclude`` are skipped; fields in ``redact``, or whose name looks sensitive, keep their
    entry but show ``REDACTED`` instead of the values.
    """
    skipped = set(exclude)
    hidden = set(redact)
    old_values = before or {}
    new_values = after or {}
    changes: dict[str, dict[str, Any]] = {}
    for field in sorted(set(old_values) | set(new_values)):
        if field in skipped:
            continue
        old = old_values.get(field)
        new = new_values.get(field)
        if before is not None and after is not None and old == new:
            continue
        if before is None and new is None:
            continue
        if after is None and old is None:
            continue
        if field in hidden or is_sensitive(field):
            changes[field] = {"old": REDACTED, "new": REDACTED}
        else:
            changes[field] = {"old": jsonable(old), "new": jsonable(new)}
    return changes
