import pytest

from core.extensions.registry import HookError, HookRegistry
from core.extensions.registry import registry as global_registry


@pytest.fixture
def reg():
    r = HookRegistry()
    r.declare("payroll.before_calculate", "Adjust the inputs before a payroll run.")
    r.declare("payroll.after_calculate")
    return r


def test_declared_hooks_are_listed(reg):
    assert reg.declared()["payroll.before_calculate"].startswith("Adjust")
    assert "payroll.after_calculate" in reg.declared()


@pytest.mark.parametrize("bad", ["payroll", "Payroll.Before", "payroll.", ".x", "payroll-before.x", ""])
def test_invalid_hook_names_are_rejected(reg, bad):
    with pytest.raises(HookError):
        reg.declare(bad)


def test_redeclaring_keeps_the_first_description(reg):
    reg.declare("payroll.before_calculate", "A different description")
    assert reg.declared()["payroll.before_calculate"].startswith("Adjust")


def test_cannot_register_on_an_undeclared_hook(reg):
    with pytest.raises(HookError, match="Unknown hook"):
        reg.register("payroll.typo", lambda: None)


def test_cannot_run_an_undeclared_hook(reg):
    with pytest.raises(HookError, match="Unknown hook"):
        reg.run("payroll.typo")


def test_register_requires_a_callable(reg):
    with pytest.raises(HookError, match="callable"):
        reg.register("payroll.before_calculate", "not callable")


def test_run_returns_results_in_order(reg):
    reg.register("payroll.after_calculate", lambda: "first")
    reg.register("payroll.after_calculate", lambda: "second")
    assert reg.run("payroll.after_calculate") == ["first", "second"]


def test_run_with_no_functions_returns_empty_list(reg):
    assert reg.run("payroll.after_calculate") == []


def test_order_value_beats_registration_order(reg):
    reg.register("payroll.after_calculate", lambda: "late", order=200)
    reg.register("payroll.after_calculate", lambda: "early", order=10)
    reg.register("payroll.after_calculate", lambda: "default")
    assert reg.run("payroll.after_calculate") == ["early", "default", "late"]


def test_arguments_are_passed_through(reg):
    reg.register("payroll.after_calculate", lambda a, b=0: a + b)
    assert reg.run("payroll.after_calculate", 2, b=3) == [5]


def test_pipe_feeds_each_result_into_the_next(reg):
    reg.register("payroll.before_calculate", lambda v: v + 1)
    reg.register("payroll.before_calculate", lambda v: v * 10)
    assert reg.pipe("payroll.before_calculate", 1) == 20


def test_pipe_passes_extra_arguments(reg):
    reg.register("payroll.before_calculate", lambda v, bonus: v + bonus)
    assert reg.pipe("payroll.before_calculate", 1, 5) == 6


def test_pipe_with_no_functions_returns_the_value(reg):
    assert reg.pipe("payroll.before_calculate", "unchanged") == "unchanged"


def test_decorator_form(reg):
    @reg.hook("payroll.after_calculate")
    def handler():
        return "ok"

    assert handler() == "ok"
    assert reg.run("payroll.after_calculate") == ["ok"]


def test_clear_removes_functions_but_keeps_declarations(reg):
    reg.register("payroll.after_calculate", lambda: 1)
    reg.clear()
    assert reg.run("payroll.after_calculate") == []
    assert "payroll.after_calculate" in reg.declared()


def test_a_failing_hook_is_not_swallowed(reg):
    def broken():
        raise RuntimeError("boom")

    reg.register("payroll.after_calculate", broken)
    with pytest.raises(RuntimeError, match="boom"):
        reg.run("payroll.after_calculate")


def test_global_registry_declares_ems_ready():
    assert "ems.ready" in global_registry.declared()
