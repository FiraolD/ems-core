"""Who is acting right now, carried in a context variable so deep code can log it.

The middleware sets it for each web request. Code that runs outside a request (Celery tasks,
management commands) has no context, and its events are recorded with no actor.

No Django imports.
"""
from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any, NamedTuple


class AuditContext(NamedTuple):
    actor_id: int | None = None
    actor_username: str = ""
    ip_address: str | None = None
    user_agent: str = ""


_NO_CONTEXT = AuditContext()  # immutable, so safe to share as the default
_current: ContextVar[AuditContext] = ContextVar("audit_context", default=_NO_CONTEXT)


def set_context(context: AuditContext):
    """Set the context and return a token for ``reset_context``."""
    return _current.set(context)


def reset_context(token) -> None:
    _current.reset(token)


def get_context() -> AuditContext:
    return _current.get()


def _valid_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return None


def client_ip(meta: Mapping[str, Any], trust_forwarded_for: bool = False) -> str | None:
    """The caller's IP address, or None when it cannot be determined.

    ``X-Forwarded-For`` is read only when the server sits behind a proxy you control, because
    otherwise any caller could write a false address into the log. Behind a proxy the first
    entry is the original client.
    """
    if trust_forwarded_for:
        forwarded = meta.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            candidate = _valid_ip(forwarded.split(",")[0])
            if candidate:
                return candidate
    remote = meta.get("REMOTE_ADDR", "")
    return _valid_ip(remote) if remote else None
