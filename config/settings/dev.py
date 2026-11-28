"""Local development. Never use these settings on a client's server."""
from .base import *  # noqa: F401,F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "insecure-dev-only-key"  # noqa: F405
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Trying the system on a laptop without PostgreSQL: set EMS_DEV_SQLITE=1 to use a local file.
# Development only. SQLite lacks the database-level protection of the audit log that PostgreSQL
# gives, so never use it for real data.
if env_bool("EMS_DEV_SQLITE"):  # noqa: F405
    DATABASES = {  # noqa: F405
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}  # noqa: F405
    }
