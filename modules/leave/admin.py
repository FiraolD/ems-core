from django.contrib import admin

from .models import LeaveAdjustment, LeaveRequest, LeaveType


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "pay_code", "uses_balance", "annual_days", "extra_day_every_years", "is_active")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    """Read-only: requests are made and decided on the leave screens so the rules are applied."""

    list_display = ("employee", "leave_type", "start_date", "end_date", "days", "status")
    list_filter = ("status", "leave_type")
    search_fields = ("employee__employee_number", "employee__full_name")
    date_hierarchy = "start_date"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LeaveAdjustment)
class LeaveAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "year", "days", "reason")
    autocomplete_fields = ("employee",)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
