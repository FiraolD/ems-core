"""Audit trail for sign-ins and role changes."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from core.audit.service import record

User = get_user_model()


@receiver(user_logged_in)
def audit_login(sender, request, user, **kwargs):
    record("login", obj=user, actor=user)


@receiver(user_logged_out)
def audit_logout(sender, request, user, **kwargs):
    if user is not None:
        record("logout", obj=user, actor=user)


@receiver(user_login_failed)
def audit_login_failed(sender, credentials, request=None, **kwargs):
    username = str((credentials or {}).get("username", ""))
    record("login_failed", object_type="accounts.User", object_repr=username)


@receiver(m2m_changed, sender=User.groups.through)
def audit_role_changes(sender, instance, action, reverse, pk_set, **kwargs):
    """Record who gained or lost a role, from either side of the relation."""
    if action not in {"post_add", "post_remove"} or not pk_set:
        return
    verb = "added" if action == "post_add" else "removed"
    if reverse:  # instance is a Group and pk_set holds user ids
        for user in User.objects.filter(pk__in=pk_set):
            record("roles_changed", obj=user, changes={"groups": {verb: [instance.name]}})
    else:  # instance is a user and pk_set holds group ids
        names = sorted(Group.objects.filter(pk__in=pk_set).values_list("name", flat=True))
        record("roles_changed", obj=instance, changes={"groups": {verb: names}})
