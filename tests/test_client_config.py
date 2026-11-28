import dataclasses
from decimal import Decimal

import pytest

from core.extensions.client import (
    ClientConfigError,
    load_client_config,
    parse_client_config,
)


def valid():
    return {
        "client": {"slug": "acme", "display_name": "Acme"},
        "company": {"legal_name": "Acme PLC", "tin": "0001234567"},
        "modules": {"enabled": ["hr", "payroll"]},
        "country": {"pack": "et"},
        "rules": {},
        "extension": {},
    }


def error_text(raw):
    with pytest.raises(ClientConfigError) as info:
        parse_client_config(raw)
    return str(info.value)


def test_valid_config_parses():
    cfg = parse_client_config(valid())
    assert cfg.slug == "acme"
    assert cfg.display_name == "Acme"
    assert cfg.company["legal_name"] == "Acme PLC"
    assert cfg.enabled_modules == ("hr", "payroll")
    assert cfg.has_module("payroll")
    assert not cfg.has_module("leave")
    assert cfg.country_pack == "et"
    assert cfg.extension_package is None


def test_optional_sections_have_defaults():
    raw = {k: valid()[k] for k in ("client", "company", "modules")}
    del raw["client"]["display_name"]
    cfg = parse_client_config(raw)
    assert cfg.display_name == "acme"
    assert cfg.country_pack == "et"
    assert dict(cfg.rule_overrides) == {}


def test_duplicate_modules_are_collapsed():
    raw = valid()
    raw["modules"]["enabled"] = ["hr", "hr", "payroll"]
    assert parse_client_config(raw).enabled_modules == ("hr", "payroll")


def test_slug_is_required_and_validated():
    raw = valid()
    del raw["client"]["slug"]
    assert "slug" in error_text(raw)
    raw["client"]["slug"] = "Acme Corp"
    assert "slug" in error_text(raw)


def test_company_legal_name_is_required():
    raw = valid()
    raw["company"] = {"tin": "1"}
    assert "legal_name" in error_text(raw)


def test_unknown_section_is_rejected():
    raw = valid()
    raw["bogus"] = {}
    assert "unknown section" in error_text(raw)


def test_unknown_module_is_rejected():
    raw = valid()
    raw["modules"]["enabled"] = ["hr", "spaceship"]
    message = error_text(raw)
    assert "spaceship" in message
    assert "Known modules" in message


def test_module_dependencies_are_enforced():
    raw = valid()
    raw["modules"]["enabled"] = ["payroll"]
    assert "payroll needs hr" in error_text(raw)


def test_modules_must_not_be_empty():
    raw = valid()
    raw["modules"]["enabled"] = []
    assert "non-empty" in error_text(raw)


def test_country_pack_must_be_two_letters():
    raw = valid()
    raw["country"]["pack"] = "ETH"
    assert "country code" in error_text(raw)


def test_extension_package_name_is_validated():
    raw = valid()
    raw["extension"] = {"package": "not-a-package"}
    assert "Python package name" in error_text(raw)
    raw["extension"] = {"package": "extension_pkg"}
    assert parse_client_config(raw).extension_package == "extension_pkg"


def test_rate_rules_must_be_quoted_text():
    raw = valid()
    raw["rules"] = {"pension_employee_rate": 0.07}
    assert "quoted text" in error_text(raw)


def test_rate_rules_become_decimals():
    raw = valid()
    raw["rules"] = {"pension_employee_rate": "0.07", "pension_employer_rate": "0.11"}
    rules = parse_client_config(raw).rule_overrides
    assert rules["pension_employee_rate"] == Decimal("0.07")
    assert isinstance(rules["pension_employer_rate"], Decimal)


@pytest.mark.parametrize("bad", ["1.5", "-0.1", "abc", "NaN", "Infinity"])
def test_rate_rules_reject_bad_values(bad):
    raw = valid()
    raw["rules"] = {"pension_employee_rate": bad}
    assert "pension_employee_rate" in error_text(raw)


def test_int_rules_are_range_checked():
    raw = valid()
    raw["rules"] = {"absence_divisor": 30}
    assert parse_client_config(raw).rule_overrides["absence_divisor"] == 30
    for bad in (0, 32, "30", True, 30.5):
        raw["rules"] = {"absence_divisor": bad}
        assert "absence_divisor" in error_text(raw)


def test_bool_rules():
    raw = valid()
    raw["rules"] = {"transport_taxable": True}
    assert parse_client_config(raw).rule_overrides["transport_taxable"] is True
    raw["rules"] = {"transport_taxable": "yes"}
    assert "transport_taxable" in error_text(raw)


def test_unknown_rule_is_rejected():
    raw = valid()
    raw["rules"] = {"absense_divisor": 30}
    assert "unknown rule" in error_text(raw)


def test_all_problems_are_reported_together():
    raw = valid()
    del raw["client"]["slug"]
    raw["modules"]["enabled"] = ["spaceship"]
    raw["rules"] = {"absence_divisor": 0}
    message = error_text(raw)
    assert "slug" in message and "spaceship" in message and "absence_divisor" in message


def test_config_is_read_only():
    cfg = parse_client_config(valid())
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.slug = "other"
    with pytest.raises(TypeError):
        cfg.rule_overrides["absence_divisor"] = 1
    with pytest.raises(TypeError):
        cfg.company["legal_name"] = "Other"


def test_load_from_file(tmp_path):
    path = tmp_path / "client.toml"
    path.write_text(
        '[client]\nslug = "acme"\n[company]\nlegal_name = "Acme PLC"\n'
        '[modules]\nenabled = ["hr"]\n[rules]\npension_employee_rate = "0.07"\n',
        encoding="utf-8",
    )
    cfg = load_client_config(path)
    assert cfg.slug == "acme"
    assert cfg.source_path == path
    assert cfg.rule_overrides["pension_employee_rate"] == Decimal("0.07")


def test_load_missing_file(tmp_path):
    with pytest.raises(ClientConfigError, match="not found"):
        load_client_config(tmp_path / "nope.toml")


def test_load_invalid_toml(tmp_path):
    path = tmp_path / "client.toml"
    path.write_text("[client\nslug = ", encoding="utf-8")
    with pytest.raises(ClientConfigError, match="not valid TOML"):
        load_client_config(path)


def test_error_names_the_file(tmp_path):
    path = tmp_path / "client.toml"
    path.write_text('[client]\nslug = "acme"\n', encoding="utf-8")
    with pytest.raises(ClientConfigError, match="client.toml"):
        load_client_config(path)


def with_extension(**extension):
    raw = valid()
    raw["extension"] = extension
    return raw


def test_extension_settings_are_read_and_cannot_be_changed():
    cfg = parse_client_config(
        with_extension(package="ext", settings={"bonus": "500.00", "days": 3, "on": True})
    )
    assert cfg.extension_settings == {"bonus": "500.00", "days": 3, "on": True}
    with pytest.raises(TypeError):
        cfg.extension_settings["bonus"] = "1"


def test_no_extension_settings_means_an_empty_read_only_mapping():
    cfg = parse_client_config(valid())
    assert dict(cfg.extension_settings) == {}


def test_decimal_numbers_in_extension_settings_are_refused_so_money_stays_exact():
    assert "quoted text" in error_text(with_extension(package="ext", settings={"bonus": 500.5}))


def test_other_extension_setting_types_are_refused():
    assert "text, a whole number or true/false" in error_text(
        with_extension(package="ext", settings={"x": [1, 2]})
    )
    assert "must be a table" in error_text(with_extension(package="ext", settings="oops"))


def test_settings_without_a_package_are_refused_and_unknown_keys_named():
    assert "no [extension] package" in error_text(with_extension(settings={"x": "1"}))
    assert "unknown key(s): pakage" in error_text(with_extension(pakage="ext"))
