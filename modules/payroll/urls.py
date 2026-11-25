from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    path("", views.index, name="index"),
    path("calculate/", views.calculate, name="calculate"),
    path("<int:year>/<int:month>/", views.run_detail, name="run"),
    path("<int:year>/<int:month>/<slug:action>/", views.act, name="act"),
]
