from django.db import Error, connection
from django.http import JsonResponse


def healthz(request):
    """Liveness: the process is up and serving requests. Does not touch the database."""
    return JsonResponse({"status": "ok"})


def readyz(request):
    """Readiness: the process can reach its database."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Error:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})
