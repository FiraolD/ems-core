"""Which rule applies on a given date.

No Django imports.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from typing import Any, NamedTuple


class RuleEntry(NamedTuple):
    key: str
    value: Any
    effective_from: date


def effective_overrides(
    base: Mapping[str, Any], entries: Iterable[RuleEntry], as_of: date
) -> dict[str, Any]:
    """``base`` (the client.toml rules) overlaid with the entries in force on ``as_of``.

    For each key the entry with the latest ``effective_from`` on or before ``as_of`` wins.
    Entries that start later are ignored. If two share a date the later one in the list wins.
    """
    merged = dict(base)
    chosen: dict[str, RuleEntry] = {}
    for entry in entries:
        if entry.effective_from > as_of:
            continue
        current = chosen.get(entry.key)
        if current is None or entry.effective_from >= current.effective_from:
            chosen[entry.key] = entry
    for key, entry in chosen.items():
        merged[key] = entry.value
    return merged


def in_force[T](
    items: Iterable[T],
    as_of: date,
    effective_from: Callable[[T], date] = lambda item: item.effective_from,
) -> T | None:
    """The item with the latest start date on or before ``as_of``; None if none has started."""
    best = None
    for item in items:
        if effective_from(item) <= as_of and (
            best is None or effective_from(item) >= effective_from(best)
        ):
            best = item
    return best
