"""A fingerprint of a payroll's figures, taken when it is locked.

If anyone later changes a figure underneath the application (directly in the database), the
fingerprint no longer matches and ``verify_run`` reports it.

No Django imports.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal


def lines_digest(period_label: str, rows: Iterable[tuple]) -> str:
    """SHA-256 over the period and each employee's figures, in a fixed order.

    ``rows`` are tuples of (employee_number, gross, tax, employee pension, employer pension,
    advance, net). Amounts are written to two decimals so 100 and 100.00 give the same result.
    """
    canonical = []
    for number, *amounts in rows:
        canonical.append([str(number), *(f"{Decimal(str(a)):.2f}" for a in amounts)])
    canonical.sort(key=lambda row: row[0])
    payload = json.dumps([period_label, canonical], separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
