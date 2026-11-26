from django.urls import path

from . import views

app_name = "overtime"

urlpatterns = [
    path("", views.my_overtime, name="mine"),
    path("record/", views.record, name="record"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
    path("approvals/", views.approvals, name="approvals"),
    path("<int:pk>/decide/", views.decide, name="decide"),
]
