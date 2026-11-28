"""One core, two differently configured companies (needs Django).

The same two employees and the same attendance are run through September 2026 payroll in a fresh
process for each client. Different modules, rules and extension behaviour must show up, and
nothing from one client may appear in the other.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("django")
pytest.importorskip("celery")

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "tests" / "_client_probe.py"


def run_probe(config: Path) -> dict:
    env = {**os.environ, "EMS_CLIENT_CONFIG": str(config), "DJANGO_SETTINGS_MODULE": "config.settings.test"}
    result = subprocess.run([sys.executable, str(PROBE)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def template():
    return run_probe(ROOT / "clients" / "_template" / "client.toml")


@pytest.fixture(scope="module")
def workshop():
    return run_probe(ROOT / "clients" / "_sample_workshop" / "client.toml")


def test_each_client_runs_only_its_own_modules(template, workshop):
    assert template["slug"] == "template" and workshop["slug"] == "sample-workshop"
    assert "modules.leave" in template["apps"] and "modules.overtime" in template["apps"]
    assert workshop["apps"] == ["modules.attendance", "modules.hr", "modules.payroll"]


def test_screens_exist_only_for_enabled_modules(template, workshop):
    assert template["urls"] == {"leave": True, "overtime": True, "attendance/report": True, "payroll": True}
    assert workshop["urls"] == {"leave": False, "overtime": False, "attendance/report": True, "payroll": True}


def test_payroll_inputs_come_only_from_enabled_modules_and_the_clients_own_extension(template, workshop):
    assert [h for h in template["hooks"] if "workshop" in h] == []
    assert any(h.startswith("modules.add_leave") or h.endswith("add_leave") for h in template["hooks"])
    assert not any(h.endswith("add_leave") or h.endswith("add_overtime") for h in workshop["hooks"])
    assert workshop["hooks"][-1].endswith("add_full_attendance_bonus")  # runs last (order 400)


def test_template_client_pays_by_its_30_day_month_and_has_no_bonus(template):
    a, b = template["lines"]["A"], template["lines"]["B"]
    assert (a["absence_deduction"], a["transport_payable"], a["paye"], a["net_salary"]) == (
        "800.00", "560.00", "2178.00", "8798.00")
    assert (b["bonus"], b["gross_earnings"], b["paye"], b["net_salary"]) == ("0.00", "12600.00", "2430.00", "9330.00")


def test_workshop_pays_by_its_own_rules_and_bonus(workshop):
    a, b = workshop["lines"]["A"], workshop["lines"]["B"]
    # two absences: no bonus, 26-day month, transport exempt from tax
    assert (a["bonus"], a["absence_deduction"], a["taxable_income"], a["paye"], a["net_salary"]) == (
        "0.00", "923.08", "11076.92", "1973.08", "8882.30")
    # perfect attendance: 500.00 bonus, tax on it inside PAYE
    assert (b["bonus"], b["bonus_tax"], b["gross_earnings"], b["paye"], b["net_salary"]) == (
        "500.00", "150.00", "13100.00", "2400.00", "9860.00")
