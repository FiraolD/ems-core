from django.apps import AppConfig


class OvertimeConfig(AppConfig):
    name = "modules.overtime"
    label = "overtime"
    verbose_name = "Overtime"

    def ready(self):
        from core.accounts.roles import registry as roles
        from core.audit.registry import register as audit_register

        for model in ("OvertimeCategory", "OvertimeEntry"):
            audit_register(self.get_model(model), exclude=("updated_at", "created_at"))

        # Entries are made and decided through the workflow so day/category rules are applied.
        # Approval is HR's for now (managers once approval can be limited to their own team).
        roles.grant("hr_manager", "overtime.view_overtimecategory", "overtime.change_overtimecategory",
                    "overtime.add_overtimecategory", "overtime.view_overtimeentry",
                    "overtime.add_overtimeentry", "overtime.approve_overtimeentry")
        for role in ("payroll_officer", "auditor"):
            roles.grant(role, "overtime.view_overtimecategory", "overtime.view_overtimeentry")

        # When payroll is enabled, this module's records feed into it.
        from django.apps import apps

        if apps.is_installed("modules.payroll"):
            from . import payroll

            payroll.register()
