import pytest

from core.audit.context import (
    AuditContext,
    client_ip,
    get_context,
    reset_context,
    set_context,
)


def test_default_context_has_no_actor():
    assert get_context() == AuditContext(None, "", None, "")


def test_set_and_reset_context():
    token = set_context(AuditContext(7, "abebe", "10.0.0.5", "Firefox"))
    try:
        assert get_context().actor_username == "abebe"
        assert get_context().actor_id == 7
    finally:
        reset_context(token)
    assert get_context().actor_id is None


def test_remote_addr_is_used_by_default():
    assert client_ip({"REMOTE_ADDR": "192.168.1.20"}) == "192.168.1.20"


def test_forwarded_for_is_ignored_unless_trusted():
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "203.0.113.9"}
    assert client_ip(meta) == "10.0.0.1"
    assert client_ip(meta, trust_forwarded_for=True) == "203.0.113.9"


def test_forwarded_for_takes_the_first_entry():
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "203.0.113.9, 10.0.0.2"}
    assert client_ip(meta, trust_forwarded_for=True) == "203.0.113.9"


def test_a_garbage_forwarded_value_falls_back_to_remote_addr():
    meta = {"REMOTE_ADDR": "10.0.0.1", "HTTP_X_FORWARDED_FOR": "not-an-ip"}
    assert client_ip(meta, trust_forwarded_for=True) == "10.0.0.1"


def test_ipv6_is_normalised():
    assert client_ip({"REMOTE_ADDR": "2001:DB8:0:0:0:0:0:1"}) == "2001:db8::1"


@pytest.mark.parametrize("meta", [{}, {"REMOTE_ADDR": ""}, {"REMOTE_ADDR": "garbage"}])
def test_missing_or_invalid_address_is_none(meta):
    assert client_ip(meta) is None
