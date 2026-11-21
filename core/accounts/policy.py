"""Login lockout and password-age rules as plain functions.

No Django imports, so the rules are easy to test. Datetimes are timezone-aware and passed in,
never read from the clock here.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple


class LockoutPolicy(NamedTuple):
    max_attempts: int = 5  # failed attempts before the account locks; 0 turns lockout off
    lock_minutes: int = 15


class LoginState(NamedTuple):
    failed_count: int
    locked_until: datetime | None
    locked_now: bool = False  # True only on the failure that caused the lock


def is_locked(locked_until: datetime | None, now: datetime) -> bool:
    return locked_until is not None and locked_until > now


def register_failure(failed_count: int, policy: LockoutPolicy, now: datetime) -> LoginState:
    """State after one more failed login.

    Reaching ``max_attempts`` locks the account for ``lock_minutes`` and starts the count
    again, so the user gets a fresh set of attempts when the lock ends.
    """
    if policy.max_attempts <= 0:
        return LoginState(0, None)
    count = failed_count + 1
    if count >= policy.max_attempts:
        return LoginState(0, now + timedelta(minutes=policy.lock_minutes), locked_now=True)
    return LoginState(count, None)


def register_success() -> LoginState:
    return LoginState(0, None)


def password_expired(changed_at: datetime | None, max_age_days: int, now: datetime) -> bool:
    """True when a password is older than ``max_age_days``. 0 turns expiry off, and a
    password with no recorded change date is never treated as expired."""
    if max_age_days <= 0 or changed_at is None:
        return False
    return now - changed_at > timedelta(days=max_age_days)
