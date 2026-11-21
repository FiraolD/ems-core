from datetime import UTC, datetime, timedelta

from core.accounts.policy import (
    LockoutPolicy,
    is_locked,
    password_expired,
    register_failure,
    register_success,
)

NOW = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
POLICY = LockoutPolicy(max_attempts=3, lock_minutes=15)


def test_failures_below_the_limit_only_count():
    state = register_failure(0, POLICY, NOW)
    assert (state.failed_count, state.locked_until, state.locked_now) == (1, None, False)
    state = register_failure(1, POLICY, NOW)
    assert (state.failed_count, state.locked_until, state.locked_now) == (2, None, False)


def test_reaching_the_limit_locks_and_resets_the_count():
    state = register_failure(2, POLICY, NOW)
    assert state.locked_now is True
    assert state.locked_until == NOW + timedelta(minutes=15)
    assert state.failed_count == 0


def test_max_attempts_zero_turns_lockout_off():
    off = LockoutPolicy(max_attempts=0)
    state = register_failure(50, off, NOW)
    assert (state.failed_count, state.locked_until, state.locked_now) == (0, None, False)


def test_success_clears_everything():
    state = register_success()
    assert (state.failed_count, state.locked_until, state.locked_now) == (0, None, False)


def test_is_locked_only_before_the_unlock_time():
    until = NOW + timedelta(minutes=5)
    assert is_locked(until, NOW) is True
    assert is_locked(until, until) is False  # the moment it ends, the user may try again
    assert is_locked(until, until + timedelta(seconds=1)) is False
    assert is_locked(None, NOW) is False


def test_password_expiry():
    old = NOW - timedelta(days=91)
    assert password_expired(old, 90, NOW) is True
    assert password_expired(NOW - timedelta(days=90), 90, NOW) is False
    assert password_expired(NOW - timedelta(days=10), 90, NOW) is False


def test_password_expiry_is_off_or_unknown_by_default():
    assert password_expired(NOW - timedelta(days=9999), 0, NOW) is False
    assert password_expired(None, 90, NOW) is False
