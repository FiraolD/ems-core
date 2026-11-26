from django.apps import AppConfig


class LeaveConfig(AppConfig):
    name = "modules.leave"
    label = "leave"
    verbose_name = "Leave"

    def ready(self):
        from core.accounts.roles import registry as roles
        from core.audit.registry import register as audit_register

        for model in ("LeaveType", "LeaveRequest", "LeaveAdjustment"):
            audit_register(self.get_model(model), exclude=("updated_at", "created_at"))

        # Requests are made and decided through the workflow (so balances and overlaps are
        # checked), not edited by hand. Approval is HR's for now: managers get it once leave
        # can be limited to their own team. Nobody deletes.
        full = ("view", "add", "change")
        roles.grant("hr_manager", *(f"leave.{a}_{m}" for m in ("leavetype", "leaveadjustment") for a in full))
        roles.grant("hr_manager", "leave.view_leaverequest", "leave.add_leaverequest", "leave.approve_leaverequest")
        for role in ("payroll_officer", "auditor"):
            roles.grant(role, "leave.view_leavetype", "leave.view_leaverequest", "leave.view_leaveadjustment")

        # When payroll is enabled, this module's records feed into it.
        from django.apps import apps

        if apps.is_installed("modules.payroll"):
            from . import payroll

            payroll.register()
