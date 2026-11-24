from django.apps import AppConfig


class HrConfig(AppConfig):
    name = "modules.hr"
    label = "hr"
    verbose_name = "Human resources"

    def ready(self):
        from core.accounts.roles import registry as roles
        from core.audit.registry import register as audit_register

        for model in ("Department", "Branch", "Position", "Employee", "SalaryRecord"):
            audit_register(self.get_model(model), exclude=("updated_at", "created_at"))

        # Nobody is granted delete: employee and salary history are kept for payroll and tax
        # records. A leaver is marked resigned/terminated/retired instead.
        full = ("view", "add", "change")
        everything = ("department", "branch", "position", "employee", "salaryrecord")
        roles.grant("hr_manager", *(f"hr.{a}_{m}" for m in everything for a in full))
        roles.grant("payroll_officer", *(f"hr.view_{m}" for m in everything))
        roles.grant("auditor", *(f"hr.view_{m}" for m in everything))
