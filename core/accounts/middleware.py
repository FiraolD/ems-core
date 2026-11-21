from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from . import policy


class ForcePasswordChangeMiddleware:
    """Send a signed-in user to the password-change page until they have set a new password.

    Applies to accounts flagged ``must_change_password`` (new accounts, admin resets) and to
    passwords older than ``EMS_PASSWORD_MAX_AGE_DAYS`` when that is set.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and self._change_required(user)
            and not self._is_exempt(request.path)
        ):
            return redirect("accounts:password_change")
        return self.get_response(request)

    @staticmethod
    def _change_required(user) -> bool:
        return user.must_change_password or policy.password_expired(
            user.password_changed_at, settings.EMS_PASSWORD_MAX_AGE_DAYS, timezone.now()
        )

    @staticmethod
    def _is_exempt(path: str) -> bool:
        allowed = {reverse("accounts:password_change"), reverse("accounts:logout")}
        return path in allowed or path.startswith(settings.STATIC_URL)
