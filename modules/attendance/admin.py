from django.contrib import admin

from .models import AttendanceRecord, PublicHoliday


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("date", "employee", "status", "source", "note")
    list_filter = ("status", "source", "date")
    search_fields = ("employee__employee_number", "employee__full_name")
    autocomplete_fields = ("employee",)
    date_hierarchy = "date"

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.recorded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ("date", "name")
