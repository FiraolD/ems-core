"""Checks that need Django installed: health endpoints and the production start-up guards."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")
pytest.importorskip("pytest_django")

ROOT = Path(__file__).resolve().parents[1]
LONG_KEY = "k" * 40


def test_healthz_does_not_need_the_database(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readyz_reports_ok_when_database_is_reachable(client):
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_load_the_template_client():
    from django.conf import settings

    assert settings.EMS_CLIENT.slug == "template"
    assert "modules.hr" in settings.INSTALLED_APPS
    assert settings.MISSING_MODULES == []


def import_prod(tmp_path, **extra):
    """Import the production settings in a fresh interpreter with exactly these variables."""
    keep = {k: v for k, v in os.environ.items()
            if k not in {"SECRET_KEY", "ALLOWED_HOSTS", "EMS_CLIENT_CONFIG"}}
    keep.update(extra)
    return subprocess.run(
        [sys.executable, "-c", "import config.settings.prod"],
        cwd=ROOT, env=keep, capture_output=True, text=True,
    )


def good_env():
    return {
        "SECRET_KEY": LONG_KEY,
        "ALLOWED_HOSTS": "hr.example.com",
        "EMS_CLIENT_CONFIG": str(ROOT / "clients" / "_template" / "client.toml"),
    }


def test_prod_starts_with_complete_configuration(tmp_path):
    result = import_prod(tmp_path, **good_env())
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("missing,fragment", [
    ("SECRET_KEY", "SECRET_KEY"),
    ("ALLOWED_HOSTS", "ALLOWED_HOSTS"),
    ("EMS_CLIENT_CONFIG", "EMS_CLIENT_CONFIG"),
])
def test_prod_refuses_to_start_without(tmp_path, missing, fragment):
    env = good_env()
    del env[missing]
    result = import_prod(tmp_path, **env)
    assert result.returncode != 0
    assert fragment in result.stderr


def test_prod_refuses_a_short_or_insecure_secret_key(tmp_path):
    for key in ("short", "insecure-" + "x" * 40):
        result = import_prod(tmp_path, **{**good_env(), "SECRET_KEY": key})
        assert result.returncode != 0
        assert "SECRET_KEY" in result.stderr


def test_prod_refuses_modules_that_are_not_installed(tmp_path):
    config = tmp_path / "client.toml"
    config.write_text(
        '[client]\nslug = "x"\n[company]\nlegal_name = "X"\n'
        '[modules]\nenabled = ["hr", "attendance"]\n',
        encoding="utf-8",
    )
    result = import_prod(tmp_path, **{**good_env(), "EMS_CLIENT_CONFIG": str(config)})
    assert result.returncode != 0
    assert "attendance" in result.stderr
