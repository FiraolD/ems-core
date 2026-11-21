"""Settings shared by every environment. The dev, prod and test files import * from here."""
import importlib.util
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.env import env, env_bool, env_int, env_list
from core.extensions.client import ClientConfigError, load_client_config

BASE_DIR = Path(__file__).resolve().parents[2]

# --- Client -------------------------------------------------------------------------
# Each installation is one client. Their client.toml decides company details, enabled
# modules, the country pack and rule overrides. Production must name it explicitly.
EMS_CLIENT_CONFIG = env("EMS_CLIENT_CONFIG") or str(BASE_DIR / "clients" / "_template" / "client.toml")
try:
    EMS_CLIENT = load_client_config(EMS_CLIENT_CONFIG)
except ClientConfigError as exc:
    raise ImproperlyConfigured(str(exc)) from exc

_CLIENT_DIR = Path(EMS_CLIENT_CONFIG).resolve().parent

# --- Modules ------------------------------------------------------------------------
# Business modules switched on for this client. A module that is enabled in client.toml
# but not built yet is skipped here and listed in MISSING_MODULES; production refuses to
# start with any missing.
MODULE_APPS = {
    "hr": "modules.hr",
    "attendance": "modules.attendance",
    "leave": "modules.leave",
    "overtime": "modules.overtime",
    "payroll": "modules.payroll",
}
_module_apps = []
MISSING_MODULES = []
for _name in EMS_CLIENT.enabled_modules:
    if importlib.util.find_spec(MODULE_APPS[_name]) is None:
        MISSING_MODULES.append(_name)
    else:
        _module_apps.append(MODULE_APPS[_name])

# --- Core ---------------------------------------------------------------------------
SECRET_KEY = env("SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # Core apps come first so their templates (sign-in pages, base layout) take precedence
    # over Django's built-in ones.
    "core.accounts",
    "core.audit",
    "core.company",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.extensions",
    *_module_apps,
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.audit.middleware.AuditContextMiddleware",
    "core.accounts.middleware.ForcePasswordChangeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# A client can override any template by placing a file with the same path in its own
# templates/ folder, next to client.toml. Client static files work the same way.
_client_templates = _CLIENT_DIR / "templates"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [_client_templates] if _client_templates.is_dir() else [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.company.context_processors.company",
            ],
        },
    },
]

# --- Database -----------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "ems"),
        "USER": env("DB_USER", "ems"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Authentication -----------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = ["core.accounts.backends.LockoutBackend"]
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "accounts:login"

# Failed sign-ins before an account locks (0 turns lockout off) and how long it stays locked.
EMS_LOCKOUT_MAX_ATTEMPTS = env_int("EMS_LOCKOUT_MAX_ATTEMPTS", 5)
EMS_LOCKOUT_MINUTES = env_int("EMS_LOCKOUT_MINUTES", 15)
# Force a password change after this many days. 0 turns expiry off.
EMS_PASSWORD_MAX_AGE_DAYS = env_int("EMS_PASSWORD_MAX_AGE_DAYS", 0)
# Trust the X-Forwarded-For header for audit-log addresses. Only when a proxy you control
# sits in front of the app, because otherwise callers could write a false address.
EMS_BEHIND_PROXY = env_bool("EMS_BEHIND_PROXY", False)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 3600)
X_FRAME_OPTIONS = "DENY"

# --- Internationalisation -----------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = env("TIME_ZONE", "Africa/Addis_Ababa")
USE_I18N = True
USE_TZ = True

# --- Static and uploaded files ------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
_client_static = _CLIENT_DIR / "static"
STATICFILES_DIRS = [_client_static] if _client_static.is_dir() else []
MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT") or BASE_DIR / "media")

# --- Background jobs ----------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_TIME_LIMIT = 15 * 60
CELERY_TIMEZONE = TIME_ZONE

# --- Logging ------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
