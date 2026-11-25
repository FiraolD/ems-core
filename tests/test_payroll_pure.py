from decimal import Decimal

import pytest

from core.extensions.registry import registry
from modules.payroll.inputs import HOOK, EmployeeInputs, gather
from modules.payroll.integrity import lines_digest

ROWS = [
    ("E001", "10600.00", "1830.00", "700.00", "1100.00", "0.00", "8070.00"),
    ("E002", "5000.00", "500.00", "350.00", "550.00", "0.00", "4150.00"),
]


def test_digest_is_stable_and_order_independent():
    assert lines_digest("September 2026", ROWS) == lines_digest("September 2026", ROWS[::-1])
    assert len(lines_digest("September 2026", ROWS)) == 64


def test_digest_ignores_how_amounts_are_written():
    other = [(n, *(str(Decimal(a)) for a in rest)) for n, *rest in ROWS]
    shorter = [("E001", 10600, 1830, 700, 1100, 0, 8070), ("E002", "5000", "500", "350", "550", "0", "4150")]
    assert lines_digest("September 2026", ROWS) == lines_digest("September 2026", other)
    assert lines_digest("September 2026", ROWS) == lines_digest("September 2026", shorter)


def test_digest_changes_if_any_figure_changes():
    base = lines_digest("September 2026", ROWS)
    for index in range(1, 7):
        changed = [list(row) for row in ROWS]
        changed[0][index] = str(Decimal(changed[0][index]) + Decimal("0.01"))
        assert lines_digest("September 2026", changed) != base


def test_digest_changes_if_an_employee_is_added_removed_or_renumbered():
    base = lines_digest("September 2026", ROWS)
    assert lines_digest("September 2026", ROWS[:1]) != base
    assert lines_digest("September 2026", [("E003", *ROWS[0][1:]), ROWS[1]]) != base


def test_digest_depends_on_the_month():
    assert lines_digest("September 2026", ROWS) != lines_digest("October 2026", ROWS)


# --- The input hook other modules use ------------------------------------------------


@pytest.fixture(autouse=True)
def clean_hooks():
    registry.clear()
    yield
    registry.clear()


def call(inputs):
    from datetime import date

    return gather(inputs, employee=object(), period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))


def test_with_nothing_registered_inputs_pass_through_unchanged():
    inputs = EmployeeInputs(bonus=Decimal("5"))
    assert call(inputs) is inputs


def test_registered_functions_adjust_inputs_in_order():
    @registry.hook(HOOK, order=10)
    def add_overtime(inputs, **kwargs):
        inputs.overtime_pay += Decimal("100")
        return inputs

    @registry.hook(HOOK, order=20)
    def double_it(inputs, **kwargs):
        inputs.overtime_pay *= 2
        return inputs

    assert call(EmployeeInputs()).overtime_pay == Decimal("200")


def test_functions_receive_the_employee_and_period():
    seen = {}

    @registry.hook(HOOK)
    def spy(inputs, *, employee, period_start, period_end):
        seen.update(employee=employee, start=period_start, end=period_end)
        return inputs

    call(EmployeeInputs())
    assert seen["start"].day == 1 and seen["end"].day == 30


def test_a_function_that_returns_the_wrong_thing_is_an_error():
    @registry.hook(HOOK)
    def broken(inputs, **kwargs):
        return None

    with pytest.raises(TypeError, match="must return EmployeeInputs"):
        call(EmployeeInputs())
