from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    path("", views.index, name="index"),
    path("calculate/", views.calculate, name="calculate"),
    path("my/", views.my_payslips, name="my_payslips"),
    path("my/<int:pk>.pdf", views.my_payslip, name="my_payslip"),
    path("payslip/<int:pk>.pdf", views.payslip, name="payslip"),
    path("<int:year>/<int:month>/payslips.pdf", views.payslips_pdf, name="payslips"),
    path("<int:year>/<int:month>/report/<slug:key>.csv", views.report_csv, name="report"),
    path("<int:year>/<int:month>/", views.run_detail, name="run"),
    path("<int:year>/<int:month>/<slug:action>/", views.act, name="act"),
]
