"""Sign-in with account lockout.

After too many wrong passwords the account is locked and even the correct password is refused
until the lock ends. The sign-in page gives the same generic error either way, so it never
reveals whether an account exists or is locked.
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import transaction
from django.utils import timezone

from core.audit.service import record

from . import policy


def lockout_policy() -> policy.LockoutPolicy:
    return policy.LockoutPolicy(
        max_attempts=settings.EMS_LOCKOUT_MAX_ATTEMPTS,
        lock_minutes=settings.EMS_LOCKOUT_MINUTES,
    )


class LockoutBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        if username is None:
            username = kwargs.get(user_model.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = user_model._default_manager.get_by_natural_key(username)
        except user_model.DoesNotExist:
            user_model().set_password(password)  # same work whether or not the account exists
            return None

        if user.is_locked:
            return None

        authenticated = super().authenticate(request, username=username, password=password)
        if authenticated is not None:
            self._record_success(user)
            return authenticated
        self._record_failure(user)
        return None

    @staticmethod
    def _record_success(user):
        if user.failed_login_count or user.locked_until:
            type(user)._default_manager.filter(pk=user.pk).update(
                failed_login_count=0, locked_until=None
            )

    @staticmethod
    def _record_failure(user):
        user_model = type(user)
        with transaction.atomic():
            current = user_model._default_manager.select_for_update().get(pk=user.pk)
            state = policy.register_failure(
                current.failed_login_count, lockout_policy(), timezone.now()
            )
            fields = {"failed_login_count": state.failed_count}
            if state.locked_now:
                fields["locked_until"] = state.locked_until
            user_model._default_manager.filter(pk=user.pk).update(**fields)
        if state.locked_now:
            record(
                "account_locked",
                obj=user,
                changes={"locked_until": {"old": None, "new": state.locked_until.isoformat()}},
            )
