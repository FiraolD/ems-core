from django.contrib import admin
from django.urls import include, path

from core.company.views import home

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("core.accounts.urls")),
    path("", include("core.health.urls")),
    path("", home, name="home"),
]
