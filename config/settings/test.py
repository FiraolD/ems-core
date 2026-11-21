"""Automated tests: in-memory SQLite so the suite runs anywhere. CI also runs the suite
against PostgreSQL with ``--ds=config.settings.dev``."""
from .base import *  # noqa: F401,F403

SECRET_KEY = "test-only-secret-key"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
LOGGING = {"version": 1, "disable_existing_loggers": True, "handlers": {}, "root": {"handlers": []}}
