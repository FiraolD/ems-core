from django.contrib import admin

from .models import OvertimeCategory, OvertimeEntry


@admin.register(OvertimeCategory)
class OvertimeCategoryAdmin(admin.ModelAdmin):
    list_display = ("kind", "multiplier", "is_active")


@admin.register(OvertimeEntry)
class OvertimeEntryAdmin(admin.ModelAdmin):
    """Read-only: entries are made and decided on the overtime screens so the rules apply."""

    list_display = ("work_date", "employee", "hours", "category", "multiplier", "status")
    list_filter = ("status", "category")
    search_fields = ("employee__employee_number", "employee__full_name")
    date_hierarchy = "work_date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
