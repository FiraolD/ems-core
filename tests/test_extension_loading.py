from pathlib import Path

import pytest

from core.extensions.client import ClientConfigError, load_client_config, load_extension
from core.extensions.registry import HookRegistry

ROOT = Path(__file__).resolve().parents[1]


def make_client(tmp_path, package=None, body=None):
    """Write a client.toml (and optionally an extension package) into tmp_path."""
    extension = f'[extension]\npackage = "{package}"\n' if package else ""
    (tmp_path / "client.toml").write_text(
        '[client]\nslug = "x"\n[company]\nlegal_name = "X"\n'
        f'[modules]\nenabled = ["hr"]\n{extension}',
        encoding="utf-8",
    )
    if package and body is not None:
        (tmp_path / package).mkdir()
        (tmp_path / package / "__init__.py").write_text(body, encoding="utf-8")
    return load_client_config(tmp_path / "client.toml")


@pytest.fixture
def reg():
    r = HookRegistry()
    r.declare("payroll.before_calculate")
    return r


def test_client_without_extension_loads_nothing(tmp_path, reg):
    assert load_extension(make_client(tmp_path), reg) is False


def test_extension_registers_its_hooks(tmp_path, reg):
    body = (
        "def register(registry):\n"
        "    registry.register('payroll.before_calculate', lambda v: v + 1)\n"
    )
    cfg = make_client(tmp_path, "ext_test_ok", body)
    assert load_extension(cfg, reg) is True
    assert reg.pipe("payroll.before_calculate", 1) == 2


def test_extension_without_register_is_an_error(tmp_path, reg):
    cfg = make_client(tmp_path, "ext_test_noreg", "x = 1\n")
    with pytest.raises(ClientConfigError, match="register"):
        load_extension(cfg, reg)


def test_missing_extension_package_is_an_error(tmp_path, reg):
    cfg = make_client(tmp_path, "ext_test_missing")
    with pytest.raises(ClientConfigError, match="Could not import"):
        load_extension(cfg, reg)


def test_extension_cannot_hook_an_undeclared_name(tmp_path, reg):
    body = "def register(registry):\n    registry.register('payroll.typo', lambda v: v)\n"
    cfg = make_client(tmp_path, "ext_test_typo", body)
    with pytest.raises(Exception, match="Unknown hook"):
        load_extension(cfg, reg)


def test_template_client_is_valid_and_loads(reg):
    cfg = load_client_config(ROOT / "clients" / "_template" / "client.toml")
    assert cfg.slug == "template"
    assert cfg.has_module("hr")
    assert load_extension(cfg, reg) is True
