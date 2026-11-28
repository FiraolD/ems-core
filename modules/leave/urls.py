from django.urls import path

from . import views

app_name = "leave"

urlpatterns = [
    path("", views.my_leave, name="mine"),
    path("request/", views.request_leave, name="request"),
    path("<int:pk>/cancel/", views.cancel, name="cancel"),
    path("approvals/", views.approvals, name="approvals"),
    path("<int:pk>/decide/", views.decide, name="decide"),
]
