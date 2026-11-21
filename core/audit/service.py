"""Write audit events. Call ``record`` wherever something worth remembering happens.

Failures are not swallowed: if the audit entry cannot be written, the caller finds out, because
an action that cannot be traced should not quietly go ahead.
"""
from . import context as audit_context
from .changes import jsonable


def record(
    action,
    *,
    obj=None,
    actor=None,
    changes=None,
    object_type="",
    object_id="",
    object_repr="",
):
    """Record one event.

    ``actor`` defaults to the signed-in user of the current web request, or nobody outside a
    request. ``obj`` fills in the object type, id and description unless given explicitly.
    """
    from .models import AuditEvent

    context = audit_context.get_context()
    if actor is not None:
        actor_id, actor_username = actor.pk, actor.get_username()
    else:
        actor_id, actor_username = context.actor_id, context.actor_username

    if obj is not None:
        object_type = object_type or f"{obj._meta.app_label}.{obj._meta.object_name}"
        object_id = object_id or ("" if obj.pk is None else str(obj.pk))
        object_repr = object_repr or str(obj)

    return AuditEvent.objects.create(
        action=action,
        actor_id=actor_id,
        actor_username=actor_username[:150],
        object_type=object_type[:100],
        object_id=object_id[:64],
        object_repr=object_repr[:255],
        changes=jsonable(changes or {}),
        ip_address=context.ip_address,
        user_agent=context.user_agent[:255],
    )
