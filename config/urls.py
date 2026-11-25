from django.conf import settings
from django.contrib import admin
from django.urls import include, path

from core.company.views import home

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("core.accounts.urls")),
    path("", include("core.health.urls")),
    path("", home, name="home"),
]

if "modules.payroll" in settings.INSTALLED_APPS:
    urlpatterns.insert(-1, path("payroll/", include("modules.payroll.urls")))

