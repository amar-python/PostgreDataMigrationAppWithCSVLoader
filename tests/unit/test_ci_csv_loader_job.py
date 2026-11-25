"""CI runs the csv_loader tool's own tests (the tool was imported in #405 and CI collected none of its tests).

The root ``pytest.ini`` has ``testpaths = tests``, so ``csv_loader/tests`` (91 tests, 8 of them need PostgreSQL) never ran
in CI: a fix to the tool had no test proving it there. The ``csv-loader`` job runs them with a PostgreSQL service through
``scripts/test_report.py --strict``, so a skipped test (the tool's database tests skip when no database is reachable)
fails the job instead of passing quietly, as everywhere else in this repository.

What must hold:
  * the job exists, waits for the ``changes`` job and is skipped only for a documentation-only change;
  * it has its own PostgreSQL service and tells the tool how to reach it (the ``PG_*`` variables the tool reads);
  * it runs ``csv_loader/tests`` through the strict accounting script and does not deselect the database tests;
  * the ``integration (postgres service)`` gate waits for it and reads its result.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gate.yml"
JOB = "csv-loader"


def jobs() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def run_text(job: dict) -> str:
    return "\n".join((s.get("run") or "") for s in job.get("steps", []))


def test_the_job_exists_waits_for_the_changes_job_and_skips_only_for_documentation():
    job = jobs()[JOB]
    needs = job["needs"] if isinstance(job["needs"], list) else [job["needs"]]
    assert "changes" in needs
    assert "needs.changes.outputs.code == 'true'" in str(job.get("if"))


def test_it_has_its_own_postgres_and_tells_the_tool_where_it_is():
    job = jobs()[JOB]
    assert job["services"]["postgres"]["image"].startswith("postgres:16")
    env = job["env"]
    for name in ("PG_HOST", "PG_PORT", "PG_USER", "PG_PASSWORD", "PG_DATABASE"):
        assert name in env, f"{name} is what csv_loader/src/config.py reads; without it the database tests cannot connect"
    assert job["services"]["postgres"]["env"].get("POSTGRES_DB") == env["PG_DATABASE"], (
        "the database the tool connects to must be created by the service")


def test_it_runs_the_tools_tests_through_the_strict_accounting_script():
    text = run_text(jobs()[JOB])
    assert "scripts/test_report.py" in text
    assert "--strict" in text, "a skipped test (no database) must fail the job"
    assert "--paths csv_loader/tests" in text
    assert '--markers "not accessibility"' in text


def test_it_does_not_deselect_the_database_tests():
    text = run_text(jobs()[JOB])
    assert "not integration" not in text and "-m unit" not in text, (
        "the database tests are the ones that prove #349 and the staging and promotion code")


def test_it_installs_the_tools_own_requirements():
    job = jobs()[JOB]
    install = [s for s in job["steps"] if "pip install" in (s.get("run") or "")]
    assert install and any("csv_loader/requirements.txt" in s["run"] for s in install)
    setup = next(s for s in job["steps"] if "setup-python" in (s.get("uses") or ""))
    assert "csv_loader/requirements.txt" in str(setup["with"].get("cache-dependency-path")), (
        "a change to the tool's requirements must refresh the pip cache")


def test_it_uploads_the_tools_reports():
    job = jobs()[JOB]
    uploads = [s for s in job["steps"] if "upload-artifact" in (s.get("uses") or "")]
    assert uploads and "csv_loader/reports" in str(uploads[0]["with"]["path"])


def test_the_gate_waits_for_the_job_and_reads_its_result():
    gate = jobs()["integration-postgres"]
    assert JOB in gate["needs"], "a red csv_loader job must turn the aggregate check red"
    text = run_text(gate)
    assert f"needs.{JOB}.result" in text
    assert "csv_loader=" in text


def test_the_root_pytest_does_not_collect_the_tool_so_the_job_is_the_only_way_it_runs():
    """If this changes (testpaths widened), the tool's markers and tests/ package name would collide with the root's."""
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "testpaths = tests" in ini
