from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("import/", views.import_view, name="import"),
    path("report/", views.report, name="report"),
    path("report/<int:year>/<int:month>.csv", views.report_csv, name="report_csv"),
]
