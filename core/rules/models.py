from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from .schema import RuleValueError, parse_rule_text, rule_choices, store_rule_value


class RuleValue(models.Model):
    """A pay rule set in the system, in force from ``effective_from`` until a later entry.

    To change a rule, add a new entry with the date it starts. Old entries stay, so past
    months can always be explained.
    """

    key = models.CharField(max_length=40, choices=rule_choices())
    value = models.CharField(max_length=40, help_text="Yes/no, a whole number, or a fraction.")
    effective_from = models.DateField(help_text="The first day this value applies.")
    note = models.CharField(max_length=255, blank=True, help_text="Why it changed.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["key", "-effective_from"]
        constraints = [
            models.UniqueConstraint(
                fields=["key", "effective_from"], name="rules_one_value_per_key_and_date"
            ),
        ]

    def __str__(self):
        return f"{self.key} = {self.value} from {self.effective_from}"

    def clean(self):
        if not self.key or not self.value:
            return
        try:
            self.value = store_rule_value(parse_rule_text(self.key, self.value))
        except RuleValueError as exc:
            raise ValidationError({"value": str(exc)}) from None

    def save(self, *args, **kwargs):
        self.full_clean(exclude=["created_at"], validate_unique=False)  # never store a bad value
        super().save(*args, **kwargs)

    @property
    def typed_value(self):
        return parse_rule_text(self.key, self.value)


class TaxSchedule(models.Model):
    """An income tax schedule in force from ``effective_from`` until a later one."""

    effective_from = models.DateField(unique=True, help_text="The first day this schedule applies.")
    note = models.CharField(max_length=255, blank=True, help_text="For example, the directive.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]

    def __str__(self):
        return f"Tax schedule from {self.effective_from}"


class TaxBand(models.Model):
    """One band of a schedule: tax = income x rate - quick deduction, within its limits."""

    schedule = models.ForeignKey(TaxSchedule, on_delete=models.CASCADE, related_name="bands")
    min_income = models.DecimalField(max_digits=14, decimal_places=2)
    max_income = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Inclusive. Leave empty for the top band.",
    )
    rate = models.DecimalField(
        max_digits=6, decimal_places=4, help_text="A fraction: 0.15 for 15%."
    )
    quick_deduction = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))

    class Meta:
        ordering = ["schedule", "min_income"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "min_income"], name="rules_one_band_per_start"
            ),
        ]

    def __str__(self):
        top = "and above" if self.max_income is None else f"to {self.max_income}"
        return f"{self.min_income} {top}: {self.rate}"
