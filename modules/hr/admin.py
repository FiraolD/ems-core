from django.contrib import admin

from .models import Branch, Department, Employee, Position, SalaryRecord


class SalaryRecordInline(admin.TabularInline):
    model = SalaryRecord
    extra = 0
    fields = (
        "effective_date",
        "basic_salary",
        "transport_allowance",
        "other_allowances",
        "other_allowances_taxable",
        "reason",
    )
    ordering = ("-effective_date",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "employee_number",
        "full_name",
        "department",
        "position",
        "employment_date",
        "status",
    )
    list_filter = ("status", "employment_type", "department", "branch")
    search_fields = ("employee_number", "full_name", "tin", "email", "phone")
    autocomplete_fields = ("user",)
    list_select_related = ("department", "position")
    date_hierarchy = "employment_date"
    inlines = [SalaryRecordInline]
    fieldsets = (
        ("Identity", {"fields": ("employee_number", "full_name", "gender", "date_of_birth", "tin")}),
        ("Position", {"fields": ("department", "position", "branch")}),
        (
            "Employment",
            {
                "fields": (
                    "employment_date",
                    "employment_type",
                    "status",
                    "termination_date",
                    "termination_reason",
                )
            },
        ),
        ("Contact and bank", {"fields": ("phone", "email", "bank_name", "bank_account_number")}),
        ("Other", {"fields": ("user", "remarks")}),
    )


class _NamedAdmin(admin.ModelAdmin):
    list_display = ("__str__", "code", "is_active")
    list_filter = ("is_active",)


@admin.register(Department)
class DepartmentAdmin(_NamedAdmin):
    search_fields = ("name", "code")


@admin.register(Branch)
class BranchAdmin(_NamedAdmin):
    search_fields = ("name", "code")


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ("title", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title",)
