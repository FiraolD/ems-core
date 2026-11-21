from django.conf import settings

from .context import AuditContext, client_ip, reset_context, set_context


class AuditContextMiddleware:
    """Make the signed-in user and the caller's address available to audit events.

    Place it after ``AuthenticationMiddleware``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        signed_in = user is not None and user.is_authenticated
        token = set_context(
            AuditContext(
                actor_id=user.pk if signed_in else None,
                actor_username=user.get_username() if signed_in else "",
                ip_address=client_ip(request.META, settings.EMS_BEHIND_PROXY),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
            )
        )
        try:
            return self.get_response(request)
        finally:
            reset_context(token)
