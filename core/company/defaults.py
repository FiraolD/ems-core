"""Turn the ``[company]`` section of client.toml into starting values for the Company record.

Used once, when the record is first created. After that the database is the source of truth
and administrators edit it in the app. No Django imports.
"""
from __future__ import annotations

from collections.abc import Mapping

TEXT_FIELDS = ("legal_name", "trade_name", "tin", "address", "city", "phone", "email")
DEFAULT_CURRENCY = "ETB"


def company_defaults(client_company: Mapping[str, str]) -> dict[str, str]:
    """Known text fields copied as-is (surrounding spaces removed); other keys are ignored.

    ``currency_code`` is upper-cased and falls back to ETB when missing or not three letters.
    """
    defaults = {
        field: client_company[field].strip()
        for field in TEXT_FIELDS
        if isinstance(client_company.get(field), str)
    }
    currency = str(client_company.get("currency_code", "")).strip().upper()
    defaults["currency_code"] = currency if len(currency) == 3 and currency.isalpha() else DEFAULT_CURRENCY
    return defaults
