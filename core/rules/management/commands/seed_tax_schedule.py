from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.rules.models import TaxBand, TaxSchedule
from countries import get_pack


class Command(BaseCommand):
    help = "Create a tax schedule from the country pack's built-in bands, from a given date."

    def add_arguments(self, parser):
        parser.add_argument(
            "--effective-from", required=True, help="First day it applies, as YYYY-MM-DD."
        )
        parser.add_argument("--note", default="Country pack default schedule")

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options["effective_from"])
        except ValueError:
            raise CommandError("--effective-from must look like 2025-07-01") from None
        if TaxSchedule.objects.filter(effective_from=start).exists():
            raise CommandError(f"A tax schedule already starts on {start}.")
        pack = get_pack(settings.EMS_CLIENT.country_pack)
        brackets = pack.default_brackets()
        pack.validate_brackets(brackets)
        with transaction.atomic():
            schedule = TaxSchedule.objects.create(effective_from=start, note=options["note"])
            TaxBand.objects.bulk_create(
                TaxBand(
                    schedule=schedule,
                    min_income=band.min_income,
                    max_income=band.max_income,
                    rate=band.rate,
                    quick_deduction=band.quick_deduction,
                )
                for band in brackets
            )
        self.stdout.write(f"Created a tax schedule with {len(brackets)} bands from {start}.")
