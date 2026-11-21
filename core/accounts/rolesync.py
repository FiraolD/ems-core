"""Apply the role registry to the database: one Group per role, holding its permissions."""
from dataclasses import dataclass, field

from django.contrib.auth.models import Group, Permission
from django.db import transaction

from .roles import RoleRegistry


@dataclass
class SyncResult:
    groups_created: list[str] = field(default_factory=list)
    groups_updated: list[str] = field(default_factory=list)
    missing_permissions: list[tuple[str, str]] = field(default_factory=list)  # (role, permission)


def sync_roles(registry: RoleRegistry) -> SyncResult:
    result = SyncResult()
    with transaction.atomic():
        for role in registry.roles().values():
            group, created = Group.objects.get_or_create(name=role.name)
            wanted = []
            for permission in sorted(role.permissions):
                app_label, codename = permission.split(".", 1)
                found = Permission.objects.filter(
                    content_type__app_label=app_label, codename=codename
                ).first()
                if found is None:
                    result.missing_permissions.append((role.name, permission))
                else:
                    wanted.append(found)
            current = set(group.permissions.values_list("pk", flat=True))
            if created:
                result.groups_created.append(role.name)
            elif current != {p.pk for p in wanted}:
                result.groups_updated.append(role.name)
            group.permissions.set(wanted)
    return result
