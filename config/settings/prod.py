"""A client's live server. Refuses to start with unsafe or incomplete configuration."""
import os

from django.core.exceptions import ImproperlyConfigured

from config.env import env_bool, env_int

from .base import *  # noqa: F401,F403

DEBUG = False

# --- Refuse to start unsafe ---------------------------------------------------------
if not SECRET_KEY or SECRET_KEY.startswith("insecure") or len(SECRET_KEY) < 32:  # noqa: F405
    raise ImproperlyConfigured("SECRET_KEY must be set to a random value of at least 32 characters.")
if not ALLOWED_HOSTS:  # noqa: F405
    raise ImproperlyConfigured("ALLOWED_HOSTS must list this server's host names or IP addresses.")
if not os.environ.get("EMS_CLIENT_CONFIG"):
    raise ImproperlyConfigured("EMS_CLIENT_CONFIG must point to the client's client.toml.")
if MISSING_MODULES:  # noqa: F405
    raise ImproperlyConfigured(
        "client.toml enables modules that are not installed: " + ", ".join(MISSING_MODULES)  # noqa: F405
    )

# Container health checks call the app on loopback.
ALLOWED_HOSTS = [*ALLOWED_HOSTS, "127.0.0.1", "localhost"]  # noqa: F405

# --- Transport security -------------------------------------------------------------
# Many installs run on a company LAN without TLS. Set EMS_HTTPS=false for those; leave it
# true (the default) whenever the server is reached over HTTPS.
EMS_HTTPS = env_bool("EMS_HTTPS", True)
SESSION_COOKIE_SECURE = EMS_HTTPS
CSRF_COOKIE_SECURE = EMS_HTTPS
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
SECURE_CONTENT_TYPE_NOSNIFF = True
if env_bool("EMS_BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Static files served by the app itself ------------------------------------------
MIDDLEWARE = [  # noqa: F405
    MIDDLEWARE[0],  # noqa: F405
    "whitenoise.middleware.WhiteNoiseMiddleware",
    *MIDDLEWARE[1:],  # noqa: F405
]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
