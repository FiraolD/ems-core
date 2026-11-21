"""Django project wiring: settings, URLs, WSGI and Celery."""
from .celery import app as celery_app

__all__ = ("celery_app",)
