"""CSV export that is safe to open in a spreadsheet.

Text that starts like a formula (= + - @) is prefixed so it shows as text instead of running, and
the file starts with a byte-order mark so Excel reads it as UTF-8 (Amharic names display correctly).

No Django imports.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Sequence
from decimal import Decimal

BOM = "﻿"
_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    text = str(value)
    if text.startswith(_FORMULA_STARTS):
        return "'" + text
    return text


def write_csv(headers: Sequence, rows: Iterable[Sequence], totals: Sequence | None = None) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([safe_cell(h) for h in headers])
    for row in rows:
        writer.writerow([safe_cell(c) for c in row])
    if totals is not None:
        writer.writerow([safe_cell(c) for c in totals])
    return BOM + out.getvalue()
