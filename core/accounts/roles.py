"""Roles and what they may do, as data.

A role becomes a Django Group, and a permission is written ``app_label.codename`` exactly as
``user.has_perm`` expects. Modules add their own grants in their ``AppConfig.ready``:

    from core.accounts.roles import registry
    registry.grant("hr_manager", "hr.view_employee", "hr.change_employee")

``python manage.py sync_roles`` applies the registry to the database. Roles are managed in code,
so a sync overwrites permissions edited by hand on a role's group; give one-off extra
permissions to a user instead.

No Django imports.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ROLE_NAME = re.compile(r"^[a-z][a-z0-9_]{1,49}$")
_PERMISSION = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class RoleError(Exception):
    """A role or permission was misnamed or not defined."""


@dataclass(frozen=True)
class Role:
    name: str
    label: str
    description: str
    permissions: frozenset[str]


class RoleRegistry:
    def __init__(self) -> None:
        self._info: dict[str, tuple[str, str]] = {}
        self._grants: dict[str, set[str]] = {}

    def define(self, name: str, label: str, description: str = "") -> None:
        """Define a role. Defining it again with the same details is harmless."""
        if not _ROLE_NAME.match(name):
            raise RoleError(f"Invalid role name {name!r}: use lowercase letters, digits and '_'")
        info = (label, description)
        if name in self._info and self._info[name] != info:
            raise RoleError(f"Role {name!r} is already defined differently")
        self._info[name] = info
        self._grants.setdefault(name, set())

    def grant(self, name: str, *permissions: str) -> None:
        if name not in self._info:
            known = ", ".join(sorted(self._info))
            raise RoleError(f"Unknown role {name!r}. Defined roles: {known}")
        for permission in permissions:
            if not _PERMISSION.match(permission):
                raise RoleError(
                    f"Invalid permission {permission!r}: write it as 'app_label.codename'"
                )
        self._grants[name].update(permissions)

    def roles(self) -> dict[str, Role]:
        return {
            name: Role(name, label, description, frozenset(self._grants[name]))
            for name, (label, description) in self._info.items()
        }

    def get(self, name: str) -> Role:
        try:
            return self.roles()[name]
        except KeyError:
            raise RoleError(f"Unknown role {name!r}") from None


registry = RoleRegistry()

registry.define("admin", "Administrator", "Manages users, roles and company settings.")
registry.define("hr_manager", "HR manager", "Manages employee records and leave.")
registry.define("payroll_officer", "Payroll officer", "Prepares and runs payroll.")
registry.define("manager", "Line manager", "Approves leave and views their team.")
registry.define("employee", "Employee", "Views their own records and payslips.")
registry.define("auditor", "Auditor", "Read-only access to records and the audit log.")

registry.grant(
    "admin",
    "accounts.manage_users",
    "accounts.view_user",
    "accounts.add_user",
    "accounts.change_user",
    "auth.view_group",
    "company.view_company",
    "company.change_company",
    "audit.view_auditevent",
)
registry.grant("auditor", "accounts.view_user", "company.view_company", "audit.view_auditevent")
registry.grant("hr_manager", "company.view_company")
registry.grant("payroll_officer", "company.view_company")
