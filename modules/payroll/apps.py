from django.apps import AppConfig


class PayrollConfig(AppConfig):
    name = "modules.payroll"
    label = "payroll"
    verbose_name = "Payroll"

    def ready(self):
        from core.accounts.roles import registry as roles
        from core.audit.registry import register as audit_register

        from . import inputs  # noqa: F401  (declares the payroll.employee_inputs hook)

        # Runs are audited by the workflow itself (calculated, submitted, locked...). The
        # rows people type in are audited field by field.
        for model in ("SalaryAdvance", "Bonus"):
            audit_register(self.get_model(model), exclude=("created_at",))

        # Calculating and locking are different people's jobs: a payroll officer prepares
        # and submits, an administrator gives final approval. Nobody deletes.
        roles.grant(
            "payroll_officer",
            "payroll.view_payrollrun",
            "payroll.view_payrollline",
            "payroll.view_payrollperiod",
            "payroll.calculate_payrollrun",
            "payroll.view_salaryadvance",
            "payroll.add_salaryadvance",
            "payroll.change_salaryadvance",
            "payroll.view_bonus",
            "payroll.add_bonus",
            "payroll.change_bonus",
        )
        roles.grant(
            "admin",
            "payroll.view_payrollrun",
            "payroll.view_payrollline",
            "payroll.view_payrollperiod",
            "payroll.lock_payrollrun",
        )
        roles.grant(
            "auditor",
            "payroll.view_payrollrun",
            "payroll.view_payrollline",
            "payroll.view_payrollperiod",
            "payroll.view_salaryadvance",
            "payroll.view_bonus",
        )
