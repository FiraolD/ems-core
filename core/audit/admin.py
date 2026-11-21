from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Read-only: the audit log can be searched and viewed, never edited."""

    list_display = ("timestamp", "actor_username", "action", "object_type", "object_repr", "ip_address")
    list_filter = ("action", "object_type")
    search_fields = ("actor_username", "object_repr", "object_id")
    date_hierarchy = "timestamp"
    readonly_fields = (
        "timestamp",
        "actor_id",
        "actor_username",
        "action",
        "object_type",
        "object_id",
        "object_repr",
        "changes",
        "ip_address",
        "user_agent",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
