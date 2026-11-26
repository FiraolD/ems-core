from django.core.management.base import BaseCommand

from modules.leave.models import LeaveType

# Starting points only. Check each against the client's contracts and the labour law that
# applies to them, then adjust under Admin > Leave types. Existing types are never changed.
STARTING_TYPES = [
    dict(name="Annual leave", pay_code="annual_leave", uses_balance=True, annual_days=16,
         extra_day_every_years=2, carry_over_max=0, prorate_first_year=True),
    dict(name="Sick leave", pay_code="sick_leave"),
    dict(name="Maternity leave", pay_code="maternity_leave"),
    dict(name="Paternity leave", pay_code="paternity_leave"),
    dict(name="Special leave", pay_code="special_leave"),
    dict(name="Unpaid leave", pay_code="unpaid_leave"),
]


class Command(BaseCommand):
    help = "Add the usual leave types if they are missing. Safe to run again."

    def handle(self, *args, **options):
        created = 0
        for values in STARTING_TYPES:
            _, was_created = LeaveType.objects.get_or_create(name=values["name"], defaults=values)
            created += was_created
        self.stdout.write(f"{created} leave type(s) added, {len(STARTING_TYPES) - created} already existed.")
        self.stdout.write("Check the day allowances against your policy before relying on balances.")
