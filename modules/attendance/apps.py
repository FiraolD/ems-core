from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    name = "modules.attendance"
    label = "attendance"
    verbose_name = "Attendance"

    def ready(self):
        from core.accounts.roles import registry as roles
        from core.audit.registry import register as audit_register

        for model in ("AttendanceRecord", "PublicHoliday"):
            audit_register(self.get_model(model), exclude=("updated_at", "created_at"))

        # HR records attendance and imports files; payroll and auditors read it. Nobody
        # deletes: a mistaken record is corrected, so the history stays complete.
        full = ("view", "add", "change")
        roles.grant("hr_manager", *(f"attendance.{a}_{m}" for m in ("attendancerecord", "publicholiday") for a in full))
        roles.grant("hr_manager", "attendance.import_attendancerecord")
        for role in ("payroll_officer", "auditor"):
            roles.grant(role, "attendance.view_attendancerecord", "attendance.view_publicholiday")

        # When payroll is enabled, this module's records feed into it.
        from django.apps import apps

        if apps.is_installed("modules.payroll"):
            from . import payroll

            payroll.register()
