from core.company.defaults import DEFAULT_CURRENCY, company_defaults


def test_known_fields_are_copied_and_trimmed():
    defaults = company_defaults({"legal_name": "  Acme PLC ", "tin": "0001234567", "city": "Adama"})
    assert defaults["legal_name"] == "Acme PLC"
    assert defaults["tin"] == "0001234567"
    assert defaults["city"] == "Adama"


def test_unknown_keys_are_ignored():
    assert "favourite_colour" not in company_defaults({"legal_name": "X", "favourite_colour": "blue"})


def test_missing_fields_are_left_out():
    defaults = company_defaults({"legal_name": "X"})
    assert "tin" not in defaults and "address" not in defaults


def test_currency_defaults_to_etb():
    assert company_defaults({"legal_name": "X"})["currency_code"] == DEFAULT_CURRENCY == "ETB"


def test_currency_is_uppercased():
    assert company_defaults({"currency_code": "usd"})["currency_code"] == "USD"


def test_bad_currency_falls_back():
    for bad in ("US", "USDX", "12$", ""):
        assert company_defaults({"currency_code": bad})["currency_code"] == "ETB"
