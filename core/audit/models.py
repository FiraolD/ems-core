from django.db import models
from django.utils import timezone


class AuditImmutableError(Exception):
    """An attempt to change or delete an audit event."""


class AuditQuerySet(models.QuerySet):
    """Blocks bulk changes. On PostgreSQL a trigger blocks them in the database too."""

    def update(self, **kwargs):
        raise AuditImmutableError("Audit events cannot be changed.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise AuditImmutableError("Audit events cannot be changed.")

    def delete(self):
        raise AuditImmutableError("Audit events cannot be deleted.")


class AuditEvent(models.Model):
    """One thing that happened: who, what, to which record, from where, and when.

    The actor is stored as an id and a username snapshot rather than a foreign key, so the log
    stays intact and readable if a user account is ever removed.
    """

    timestamp = models.DateTimeField(default=timezone.now, db_index=True, editable=False)
    actor_id = models.BigIntegerField(null=True, blank=True, db_index=True, editable=False)
    actor_username = models.CharField(max_length=150, blank=True, editable=False)
    action = models.CharField(max_length=64, db_index=True, editable=False)
    object_type = models.CharField(max_length=100, blank=True, editable=False)
    object_id = models.CharField(max_length=64, blank=True, editable=False)
    object_repr = models.CharField(max_length=255, blank=True, editable=False)
    changes = models.JSONField(default=dict, blank=True, editable=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True, editable=False)
    user_agent = models.CharField(max_length=255, blank=True, editable=False)

    objects = AuditQuerySet.as_manager()

    class Meta:
        db_table = "audit_auditevent"
        ordering = ["-timestamp", "-id"]
        default_permissions = ("view",)  # nobody is ever granted add, change or delete
        indexes = [models.Index(fields=["object_type", "object_id"], name="audit_object_idx")]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M:%S} {self.actor_username or 'system'} {self.action}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditImmutableError("Audit events cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditImmutableError("Audit events cannot be deleted.")
