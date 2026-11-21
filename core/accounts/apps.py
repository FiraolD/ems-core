from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "core.accounts"
    label = "accounts"
    verbose_name = "Accounts"

    def ready(self):
        from core.audit.registry import register as audit_register

        from . import signals  # noqa: F401  (connects the login and role-change handlers)

        audit_register(
            self.get_model("User"),
            exclude=("last_login", "failed_login_count"),
            redact=("password",),
        )
