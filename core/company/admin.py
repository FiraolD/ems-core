from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse

from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    """There is only ever one company, so the list page jumps straight to its edit form."""

    list_display = ("legal_name", "tin", "city", "currency_code")

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        company = Company.get()
        return redirect(reverse("admin:company_company_change", args=[company.pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
