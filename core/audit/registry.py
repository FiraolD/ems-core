"""Automatic audit trail for a model: ``register(MyModel)`` in the app's ``ready()``.

Every create, update and delete made through the ORM (``save()`` and ``delete()``) is recorded
with the fields that changed. Bulk operations such as ``QuerySet.update()`` skip Django's
signals; where one matters, call ``core.audit.service.record`` yourself.
"""
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save

from .changes import diff_values
from .service import record


class _Options(NamedTuple):
    exclude: frozenset[str]
    redact: frozenset[str]


_OPTIONS: dict[str, _Options] = {}


def register(model, *, exclude: Iterable[str] = (), redact: Iterable[str] = ()) -> None:
    """Audit ``model``. ``exclude`` lists fields not worth logging (counters, timestamps);
    ``redact`` lists fields whose values must never be written to the log."""
    label = model._meta.label_lower
    _OPTIONS[label] = _Options(frozenset(exclude), frozenset(redact))
    pre_save.connect(_pre_save, sender=model, dispatch_uid=f"audit-pre-save-{label}")
    post_save.connect(_post_save, sender=model, dispatch_uid=f"audit-post-save-{label}")
    post_delete.connect(_post_delete, sender=model, dispatch_uid=f"audit-post-delete-{label}")


def _as_stored(field, value):
    """Money as the database will hold it (12000 -> 12000.00), so a log line reads the same
    whether the value came from the database or from an unsaved object."""
    if isinstance(field, models.DecimalField) and value is not None:
        try:
            exponent = Decimal(1).scaleb(-field.decimal_places)
            return field.to_python(value).quantize(exponent)
        except (InvalidOperation, ValidationError, TypeError, AttributeError):
            return value
    return value


def _values(instance, only=None) -> dict:
    return {
        field.attname: _as_stored(field, getattr(instance, field.attname))
        for field in instance._meta.concrete_fields
        if only is None or field.attname in only
    }


def _attnames(model, update_fields):
    """Column names covered by a partial save, or None for a full save."""
    if not update_fields:
        return None
    return {model._meta.get_field(name).attname for name in update_fields}


def _pre_save(sender, instance, raw=False, update_fields=None, **kwargs):
    instance._audit_before = None
    if raw or instance.pk is None:
        return
    row = sender._base_manager.filter(pk=instance.pk).values().first()
    if row is not None:
        names = _attnames(sender, update_fields)
        instance._audit_before = row if names is None else {k: row[k] for k in names}


def _post_save(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw:
        return
    options = _OPTIONS[sender._meta.label_lower]
    before = getattr(instance, "_audit_before", None)
    instance._audit_before = None
    names = _attnames(sender, update_fields)
    after = _values(instance, names)
    if created or before is None:
        action = "create"
        changes = diff_values(None, after, exclude=options.exclude, redact=options.redact)
    else:
        action = "update"
        changes = diff_values(before, after, exclude=options.exclude, redact=options.redact)
        if not changes:
            return
    record(action, obj=instance, changes=changes)


def _post_delete(sender, instance, **kwargs):
    options = _OPTIONS[sender._meta.label_lower]
    changes = diff_values(_values(instance), None, exclude=options.exclude, redact=options.redact)
    record("delete", obj=instance, changes=changes)
