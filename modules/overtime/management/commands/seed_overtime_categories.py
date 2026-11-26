from django.core.management.base import BaseCommand

from modules.overtime import logic
from modules.overtime.models import OvertimeCategory

# Starting points only: confirm the multipliers against the labour law and the client's
# contracts, then adjust under Admin > Overtime categories. Existing rows are never changed.
STARTING = [(logic.NORMAL, "1.25"), (logic.NIGHT, "1.50"), (logic.REST_DAY, "2.00"), (logic.HOLIDAY, "2.50")]


class Command(BaseCommand):
    help = "Add the four overtime categories if they are missing. Safe to run again."

    def handle(self, *args, **options):
        added = sum(
            OvertimeCategory.objects.get_or_create(kind=kind, defaults={"multiplier": rate})[1]
            for kind, rate in STARTING
        )
        self.stdout.write(f"{added} categor{'y' if added == 1 else 'ies'} added, {4 - added} already existed.")
        self.stdout.write("Check the multipliers against your policy before paying overtime.")
