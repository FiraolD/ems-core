from django.core.management.base import BaseCommand, CommandError

from core.accounts.roles import registry
from core.accounts.rolesync import sync_roles


class Command(BaseCommand):
    help = "Create or update the role groups defined in code. Safe to run repeatedly."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail if a role grants a permission that does not exist.",
        )

    def handle(self, *args, **options):
        result = sync_roles(registry)
        for name in result.groups_created:
            self.stdout.write(f"Created role: {name}")
        for name in result.groups_updated:
            self.stdout.write(f"Updated role: {name}")
        if not (result.groups_created or result.groups_updated):
            self.stdout.write("Roles already up to date.")
        for role, permission in result.missing_permissions:
            self.stderr.write(f"Role {role} grants unknown permission {permission}")
        if result.missing_permissions and options["strict"]:
            raise CommandError(f"{len(result.missing_permissions)} unknown permission(s).")
