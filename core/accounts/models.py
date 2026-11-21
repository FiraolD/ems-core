from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from . import policy


class User(AbstractUser):
    """The login account. Replacing Django's user later is painful, so it is custom from day one."""

    must_change_password = models.BooleanField(
        default=False,
        help_text="The user must choose a new password at their next sign-in.",
    )
    failed_login_count = models.PositiveSmallIntegerField(default=0, editable=False)
    locked_until = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Sign-in is refused until this time. Clear it to unlock the account.",
    )
    password_changed_at = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        permissions = [("manage_users", "Can manage users and roles")]

    @property
    def is_locked(self) -> bool:
        return policy.is_locked(self.locked_until, timezone.now())

    def set_password(self, raw_password):
        super().set_password(raw_password)
        self.password_changed_at = timezone.now()
