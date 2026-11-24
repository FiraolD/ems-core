from django import forms
from django.conf import settings
from django.contrib import admin
from django.core.exceptions import ValidationError

from countries import get_pack

from .models import RuleValue, TaxBand, TaxSchedule


@admin.register(RuleValue)
class RuleValueAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "effective_from", "note")
    list_filter = ("key",)
    ordering = ("key", "-effective_from")


class TaxBandFormSet(forms.BaseInlineFormSet):
    """Check the bands together: no gaps, rising rates, continuous tax."""

    def clean(self):
        super().clean()
        if any(self.errors):
            return  # fix the individual fields first
        pack = get_pack(settings.EMS_CLIENT.country_pack)
        bands = []
        for form in self.forms:
            data = form.cleaned_data
            if not data or data.get("DELETE"):
                continue
            bands.append(
                pack.Bracket(
                    data["min_income"], data.get("max_income"), data["rate"], data["quick_deduction"]
                )
            )
        if not bands:
            raise ValidationError("A tax schedule needs at least one band.")
        try:
            pack.validate_brackets(bands)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None


class TaxBandInline(admin.TabularInline):
    model = TaxBand
    formset = TaxBandFormSet
    extra = 0
    min_num = 1
    ordering = ("min_income",)


@admin.register(TaxSchedule)
class TaxScheduleAdmin(admin.ModelAdmin):
    list_display = ("effective_from", "note", "band_count")
    inlines = [TaxBandInline]

    @admin.display(description="Bands")
    def band_count(self, obj):
        return obj.bands.count()
