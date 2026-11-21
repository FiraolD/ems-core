from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class ExtensionsConfig(AppConfig):
    name = "core.extensions"
    label = "extensions"
    verbose_name = "Client extensions"

    def ready(self):
        from django.conf import settings

        from .client import ClientConfigError, load_extension
        from .registry import registry

        try:
            load_extension(settings.EMS_CLIENT, registry)
        except ClientConfigError as exc:
            raise ImproperlyConfigured(str(exc)) from exc
        registry.run("ems.ready")
