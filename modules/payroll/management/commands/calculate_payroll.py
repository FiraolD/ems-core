from django.core.management.base import BaseCommand, CommandError

from modules.payroll import service


class Command(BaseCommand):
    help = "Calculate (or recalculate) the draft payroll for a month."

    def add_arguments(self, parser):
        parser.add_argument("year", type=int)
        parser.add_argument("month", type=int)

    def handle(self, *args, **options):
        try:
            run = service.calculate_run(options["year"], options["month"])
        except service.PayrollError as exc:
            raise CommandError(str(exc)) from None
        totals = service.run_totals(run)
        self.stdout.write(
            f"{run.period.label}: {totals.employees} employees, net pay {totals.net_salary}, "
            f"{len(run.skipped)} skipped."
        )
        for item in run.skipped:
            self.stderr.write(f"Skipped {item['employee_number']} {item['name']}: {item['reason']}")
