import pytest

from core.accounts.roles import RoleError, RoleRegistry
from core.accounts.roles import registry as default_registry


@pytest.fixture
def reg():
    return RoleRegistry()


def test_define_and_grant(reg):
    reg.define("clerk", "Clerk", "Does paperwork.")
    reg.grant("clerk", "hr.view_employee", "hr.change_employee")
    role = reg.get("clerk")
    assert role.label == "Clerk"
    assert role.permissions == frozenset({"hr.view_employee", "hr.change_employee"})


def test_redefining_identically_is_harmless_but_differently_is_an_error(reg):
    reg.define("clerk", "Clerk", "Does paperwork.")
    reg.define("clerk", "Clerk", "Does paperwork.")
    with pytest.raises(RoleError, match="already defined"):
        reg.define("clerk", "Clerk", "Something else")


@pytest.mark.parametrize("bad", ["Clerk", "1clerk", "c", "has space", "has-dash", ""])
def test_invalid_role_names(reg, bad):
    with pytest.raises(RoleError, match="Invalid role name"):
        reg.define(bad, "x")


def test_granting_to_an_undefined_role_fails(reg):
    with pytest.raises(RoleError, match="Unknown role"):
        reg.grant("ghost", "hr.view_employee")


@pytest.mark.parametrize("bad", ["view_employee", "hr.View", "hr.", ".view", "hr.view-employee"])
def test_invalid_permission_strings(reg, bad):
    reg.define("clerk", "Clerk")
    with pytest.raises(RoleError, match="Invalid permission"):
        reg.grant("clerk", bad)


def test_a_failed_grant_adds_nothing(reg):
    reg.define("clerk", "Clerk")
    with pytest.raises(RoleError):
        reg.grant("clerk", "hr.view_employee", "bad permission")
    assert reg.get("clerk").permissions == frozenset()


def test_grants_accumulate_and_roles_are_snapshots(reg):
    reg.define("clerk", "Clerk")
    reg.grant("clerk", "hr.view_employee")
    snapshot = reg.roles()["clerk"]
    reg.grant("clerk", "hr.change_employee")
    assert snapshot.permissions == frozenset({"hr.view_employee"})
    assert len(reg.get("clerk").permissions) == 2


def test_get_unknown_role(reg):
    with pytest.raises(RoleError, match="Unknown role"):
        reg.get("ghost")


def test_default_roles_exist():
    roles = default_registry.roles()
    assert {"admin", "hr_manager", "payroll_officer", "manager", "employee", "auditor"} <= set(roles)


def test_default_admin_can_manage_users_and_see_the_audit_log():
    admin = default_registry.get("admin").permissions
    assert {"accounts.manage_users", "audit.view_auditevent", "company.change_company"} <= admin


def test_auditor_is_read_only():
    auditor = default_registry.get("auditor").permissions
    assert "audit.view_auditevent" in auditor
    assert not any(p.split(".")[1].startswith(("add_", "change_", "delete_")) for p in auditor)
