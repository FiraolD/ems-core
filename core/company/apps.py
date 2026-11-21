from django.apps import AppConfig


class CompanyConfig(AppConfig):
    name = "core.company"
    label = "company"
    verbose_name = "Company"

    def ready(self):
        from core.audit.registry import register as audit_register

        audit_register(self.get_model("Company"), exclude=("updated_at",))
