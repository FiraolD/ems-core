from django.conf import settings
from django.db import models

from .defaults import company_defaults


class CompanyDeletionError(Exception):
    """The company record cannot be deleted."""


class Company(models.Model):
    """The one company this installation belongs to (each client has its own install).

    Always stored as row 1. ``Company.get()`` creates it on first use from the ``[company]``
    section of client.toml; after that administrators edit it in the app.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    legal_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, blank=True)
    tin = models.CharField("TIN", max_length=20, blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    currency_code = models.CharField(max_length=3, default="ETB")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "company"
        constraints = [models.CheckConstraint(condition=models.Q(id=1), name="company_is_single")]

    def __str__(self):
        return self.legal_name

    @classmethod
    def get(cls) -> "Company":
        company, _ = cls.objects.get_or_create(
            id=1, defaults=company_defaults(settings.EMS_CLIENT.company)
        )
        return company

    def save(self, *args, **kwargs):
        self.id = 1
        # A fresh Company(...) always carries pk 1, so Django would try to INSERT it. If the
        # row already exists, this is an update of that row.
        if self._state.adding and not kwargs.get("force_insert"):
            if type(self).objects.filter(pk=1).exists():
                self._state.adding = False
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise CompanyDeletionError("The company record cannot be deleted.")
