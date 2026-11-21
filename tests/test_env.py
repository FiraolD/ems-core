import pytest

pytest.importorskip("celery")  # config/__init__.py imports Celery

from config.env import env, env_bool, env_int, env_list  # noqa: E402


def test_env_default(monkeypatch):
    monkeypatch.delenv("EMS_TEST_VAR", raising=False)
    assert env("EMS_TEST_VAR") is None
    assert env("EMS_TEST_VAR", "fallback") == "fallback"
    monkeypatch.setenv("EMS_TEST_VAR", "value")
    assert env("EMS_TEST_VAR", "fallback") == "value"


@pytest.mark.parametrize("raw,expected", [("true", True), ("1", True), ("YES", True),
                                          ("false", False), ("0", False), ("off", False), ("", False)])
def test_env_bool(monkeypatch, raw, expected):
    monkeypatch.setenv("EMS_TEST_FLAG", raw)
    assert env_bool("EMS_TEST_FLAG") is expected


def test_env_bool_default_and_error(monkeypatch):
    monkeypatch.delenv("EMS_TEST_FLAG", raising=False)
    assert env_bool("EMS_TEST_FLAG", True) is True
    monkeypatch.setenv("EMS_TEST_FLAG", "maybe")
    with pytest.raises(ValueError, match="EMS_TEST_FLAG"):
        env_bool("EMS_TEST_FLAG")


def test_env_int(monkeypatch):
    monkeypatch.delenv("EMS_TEST_NUM", raising=False)
    assert env_int("EMS_TEST_NUM", 7) == 7
    monkeypatch.setenv("EMS_TEST_NUM", "42")
    assert env_int("EMS_TEST_NUM", 7) == 42
    monkeypatch.setenv("EMS_TEST_NUM", "abc")
    with pytest.raises(ValueError, match="EMS_TEST_NUM"):
        env_int("EMS_TEST_NUM", 7)


def test_env_list(monkeypatch):
    monkeypatch.delenv("EMS_TEST_LIST", raising=False)
    assert env_list("EMS_TEST_LIST") == []
    assert env_list("EMS_TEST_LIST", ["a"]) == ["a"]
    monkeypatch.setenv("EMS_TEST_LIST", " a, b ,,c ")
    assert env_list("EMS_TEST_LIST") == ["a", "b", "c"]
