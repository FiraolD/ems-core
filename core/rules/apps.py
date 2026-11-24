from django.apps import AppConfig


class RulesConfig(AppConfig):
    name = "core.rules"
    label = "rules"
    verbose_name = "Pay rules"

    def ready(self):
        from core.accounts.roles import registry as roles
        from core.audit.registry import register as audit_register

        for model in ("RuleValue", "TaxSchedule", "TaxBand"):
            audit_register(self.get_model(model), exclude=("created_at",))

        # Changing tax and pension rules is sensitive: administrators only. Payroll officers
        # and auditors can see them. Nobody deletes: history explains past payrolls.
        models = ("rulevalue", "taxschedule", "taxband")
        roles.grant("admin", *(f"rules.{a}_{m}" for m in models for a in ("view", "add", "change")))
        roles.grant("payroll_officer", *(f"rules.view_{m}" for m in models))
        roles.grant("auditor", *(f"rules.view_{m}" for m in models))
