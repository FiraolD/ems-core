"""Local development. Never use these settings on a client's server."""
from .base import *  # noqa: F401,F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "insecure-dev-only-key"  # noqa: F405
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
