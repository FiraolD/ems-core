from django.contrib import admin

from .models import Bonus, PayrollLine, PayrollRun, SalaryAdvance


class ReadOnlyAdmin(admin.ModelAdmin):
    """Payroll results are made by the payroll screens, never typed or edited here."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PayrollRun)
class PayrollRunAdmin(ReadOnlyAdmin):
    list_display = ("period", "status", "calculated_at", "locked_at", "locked_by")
    list_filter = ("status",)


@admin.register(PayrollLine)
class PayrollLineAdmin(ReadOnlyAdmin):
    list_display = ("run", "employee_number", "employee_name", "gross_earnings", "paye", "net_salary")
    list_filter = ("run",)
    search_fields = ("employee_number", "employee_name")


@admin.register(SalaryAdvance)
class SalaryAdvanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "year", "month", "amount", "note")
    list_filter = ("year", "month")
    autocomplete_fields = ("employee",)


@admin.register(Bonus)
class BonusAdmin(admin.ModelAdmin):
    list_display = ("employee", "year", "month", "amount", "approved", "reason")
    list_filter = ("year", "month", "approved")
    autocomplete_fields = ("employee",)
