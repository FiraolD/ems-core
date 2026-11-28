"""Start the real system under whichever client EMS_CLIENT_CONFIG names, run the same September
2026 payroll, and print what happened as JSON. Used by tests/test_client_isolation_django.py,
one fresh process per client, so nothing can leak between them. Not a test itself."""
import json
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.core.management import call_command  # noqa: E402
from django.urls import Resolver404, resolve  # noqa: E402

from core.extensions.registry import registry  # noqa: E402
from modules.attendance.models import AttendanceRecord  # noqa: E402
from modules.hr.models import Employee, SalaryRecord  # noqa: E402
from modules.payroll import service  # noqa: E402
from modules.payroll.inputs import HOOK  # noqa: E402
from modules.payroll.models import PayrollLine  # noqa: E402

call_command("migrate", verbosity=0)


def make(number, absent_days):
    emp = Employee.objects.create(employee_number=number, full_name=f"Person {number}", employment_date=date(2020, 1, 1))
    SalaryRecord.objects.create(
        employee=emp, effective_date=date(2020, 1, 1), basic_salary=Decimal("12000"), transport_allowance=Decimal("600")
    )
    for day in range(1, 1 + absent_days):
        AttendanceRecord.objects.create(employee=emp, date=date(2026, 9, day), status="absent")


make("A", absent_days=2)  # two absent days
make("B", absent_days=0)  # perfect attendance
service.calculate_run(2026, 9)


def has_url(path):
    try:
        resolve(path)
        return True
    except Resolver404:
        return False


fields = ("absence_deduction", "transport_payable", "bonus", "bonus_tax", "gross_earnings", "taxable_income", "paye", "net_salary")
print(json.dumps({
    "slug": settings.EMS_CLIENT.slug,
    "modules": list(settings.EMS_CLIENT.enabled_modules),
    "apps": sorted(a for a in settings.INSTALLED_APPS if a.startswith("modules.")),
    "urls": {name: has_url(f"/{name}/") for name in ("leave", "overtime", "attendance/report", "payroll")},
    "hooks": [fn.__module__.split(".")[0] + "." + fn.__name__ for fn in registry.functions(HOOK)],
    "lines": {
        line.employee_number: {f: str(getattr(line, f)) for f in fields} for line in PayrollLine.objects.all()
    },
}))
