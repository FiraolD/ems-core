import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from core.audit.changes import REDACTED, diff_values, is_sensitive, jsonable


def test_unchanged_fields_are_left_out():
    before = {"name": "Abebe", "salary": Decimal("1000.00")}
    after = {"name": "Abebe", "salary": Decimal("1200.00")}
    assert diff_values(before, after) == {"salary": {"old": "1000.00", "new": "1200.00"}}


def test_no_changes_gives_an_empty_diff():
    assert diff_values({"a": 1}, {"a": 1}) == {}


def test_create_lists_every_set_field():
    changes = diff_values(None, {"name": "Abebe", "middle": None, "age": 30})
    assert changes == {
        "age": {"old": None, "new": 30},
        "name": {"old": None, "new": "Abebe"},
    }


def test_delete_lists_every_set_field_as_removed():
    changes = diff_values({"name": "Abebe", "middle": None}, None)
    assert changes == {"name": {"old": "Abebe", "new": None}}


def test_a_field_cleared_to_none_is_a_change():
    assert diff_values({"phone": "0911"}, {"phone": None}) == {"phone": {"old": "0911", "new": None}}


def test_exclude_skips_fields():
    changes = diff_values({"a": 1, "last_login": 1}, {"a": 2, "last_login": 2}, exclude=["last_login"])
    assert set(changes) == {"a"}


def test_sensitive_fields_are_redacted_automatically():
    changes = diff_values({"password": "old-hash"}, {"password": "new-hash"})
    assert changes == {"password": {"old": REDACTED, "new": REDACTED}}
    assert "hash" not in json.dumps(changes)


def test_explicit_redact_list():
    changes = diff_values({"tin": "111"}, {"tin": "222"}, redact=["tin"])
    assert changes["tin"] == {"old": REDACTED, "new": REDACTED}


def test_a_redacted_field_that_did_not_change_is_still_skipped():
    assert diff_values({"password": "same"}, {"password": "same"}) == {}


def test_is_sensitive():
    for name in ("password", "Password_Hash", "api_key", "auth_token", "client_secret"):
        assert is_sensitive(name)
    for name in ("username", "salary", "passport"):
        assert not is_sensitive(name)


def test_jsonable_handles_common_field_types():
    value = {
        "when": datetime(2026, 11, 21, 9, 0, tzinfo=UTC),
        "day": date(2026, 11, 21),
        "pay": Decimal("1234.50"),
        "id": UUID("12345678-1234-5678-1234-567812345678"),
        "tags": {"b", "a"},
        "raw": b"\x00\x01",
        "nested": {"x": (1, 2)},
    }
    result = jsonable(value)
    json.dumps(result)  # must not raise
    assert result["when"] == "2026-11-21T09:00:00+00:00"
    assert result["pay"] == "1234.50"
    assert result["tags"] == ["a", "b"]
    assert result["raw"] == "[binary]"
    assert result["nested"] == {"x": [1, 2]}


def test_money_keeps_exact_digits():
    assert jsonable(Decimal("0.1") + Decimal("0.2")) == "0.3"
