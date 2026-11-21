from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render


@login_required
def home(request):
    return render(request, "company/home.html", {"modules": settings.EMS_CLIENT.enabled_modules})
