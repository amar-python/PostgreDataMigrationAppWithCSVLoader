"""#326 (SE-05): scripts/security_audit.py fails CI on a known-vulnerable dependency.

pip-audit and npm audit need the network, so these tests feed the script canned output. What they pin is the policy:

  * a finding blocks, unless it is on the allow-list and the entry has not expired;
  * an expired allow-list entry fails the run by itself, so an exception cannot be forgotten;
  * the audit fails CLOSED: if pip-audit or npm audit cannot run, or a requirements file audits no package, the
    result is "could not audit" (exit 2), never a pass. (test_report.py once printed PASS with 0 tests run.)
  * the requirements files come from git, not from a list, so a new one is audited without anyone remembering.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from scripts import security_audit as sa

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
TODAY = dt.date(2026, 11, 23)


def pip_json(*deps: dict) -> str:
    return json.dumps({"dependencies": list(deps), "fixes": []})


CLEAN = pip_json({"name": "fastapi", "version": "0.162.5", "vulns": []})
VULNERABLE = pip_json(
    {"name": "fastapi", "version": "0.162.5", "vulns": []},
    {"name": "requests", "version": "2.30.0", "vulns": [
        {"id": "PYSEC-2023-74", "aliases": ["CVE-2023-32681", "GHSA-j8r2-6x86-q33q"], "fix_versions": ["2.31.0"],
         "description": "Unintended leak of Proxy-Authorization header"}]})


def npm_json(**vulns) -> str:
    return json.dumps({"vulnerabilities": vulns, "metadata": {"vulnerabilities": {"total": len(vulns)}}})


NPM_HIGH = npm_json(
    lodash={"name": "lodash", "severity": "high", "via": [
        {"source": 1, "name": "lodash", "title": "Prototype pollution", "severity": "high",
         "url": "https://github.com/advisories/GHSA-p6mc-m468-83gw"}], "fixAvailable": True},
    left_pad={"name": "left-pad", "severity": "moderate", "via": [
        {"source": 2, "name": "left-pad", "title": "Meh", "severity": "moderate",
         "url": "https://github.com/advisories/GHSA-aaaa-bbbb-cccc"}], "fixAvailable": False})


# --- parsing -----------------------------------------------------------------------------------------------------

def test_pip_audit_output_with_a_vulnerable_package_yields_one_finding_with_its_aliases():
    findings = sa.parse_pip_audit(VULNERABLE, "api/requirements.txt")
    assert [(f.package, f.version, f.advisory) for f in findings] == [("requests", "2.30.0", "PYSEC-2023-74")]
    assert {"CVE-2023-32681", "GHSA-j8r2-6x86-q33q"} <= set(findings[0].aliases)
    assert findings[0].fix == "2.31.0" and findings[0].source == "api/requirements.txt"


def test_an_advisory_that_pip_audit_lists_twice_is_one_finding():
    """Seen on live output for `requests==2.30.0`: every advisory came back twice, so '8 blocking' meant 4."""
    dup = {"id": "PYSEC-2023-74", "aliases": ["CVE-2023-32681"], "fix_versions": ["2.31.0"]}
    twice = pip_json({"name": "requests", "version": "2.30.0", "vulns": [dup, dict(dup)]})
    assert len(sa.parse_pip_audit(twice, "x.txt")) == 1


def test_clean_pip_audit_output_yields_no_findings():
    assert sa.parse_pip_audit(CLEAN, "x.txt") == []


def test_a_requirements_file_that_audits_no_package_is_an_error_not_a_pass():
    with pytest.raises(sa.AuditError, match="audited no package"):
        sa.parse_pip_audit(pip_json(), "requirements-dev.txt")


def test_pip_audit_output_that_is_not_json_is_an_error():
    with pytest.raises(sa.AuditError, match="not JSON"):
        sa.parse_pip_audit("Traceback (most recent call last): ...", "x.txt")


def test_npm_audit_keeps_high_and_critical_and_drops_the_rest():
    findings = sa.parse_npm_audit(NPM_HIGH, "csv-table-hub-main")
    assert [(f.package, f.advisory) for f in findings] == [("lodash", "GHSA-p6mc-m468-83gw")]


def test_npm_audit_error_payload_is_an_error_not_a_pass():
    payload = json.dumps({"error": {"code": "ENOTFOUND", "summary": "request to registry failed"}})
    with pytest.raises(sa.AuditError, match="ENOTFOUND"):
        sa.parse_npm_audit(payload, "csv-table-hub-main")


def test_npm_audit_with_no_vulnerabilities_key_is_an_error():
    with pytest.raises(sa.AuditError):
        sa.parse_npm_audit("{}", "csv-table-hub-main")


# --- the allow-list ----------------------------------------------------------------------------------------------

ALLOW = """
# comments and blank lines are ignored

PYSEC-2023-74   2026-12-31   requests: not reachable, we never send Proxy-Authorization (owner, 2026-11-23)
GHSA-old-old-old 2026-01-01  an exception that has expired
"""


def test_the_allowlist_reads_id_expiry_and_reason():
    entries = sa.parse_allowlist(ALLOW)
    assert [(e.advisory, e.expires.isoformat()) for e in entries] == [
        ("PYSEC-2023-74", "2026-12-31"), ("GHSA-old-old-old", "2026-01-01")]
    assert "not reachable" in entries[0].reason


@pytest.mark.parametrize("line", ["PYSEC-1", "PYSEC-1 not-a-date because", "PYSEC-1 2026-12-31", "2026-12-31 PYSEC-1 why"])
def test_a_malformed_allowlist_line_is_an_error(line):
    with pytest.raises(sa.AuditError, match="allow-list"):
        sa.parse_allowlist(line)


def test_an_allowlisted_finding_does_not_block_until_the_entry_expires():
    findings = sa.parse_pip_audit(VULNERABLE, "api/requirements.txt")
    result = sa.evaluate(findings, sa.parse_allowlist(ALLOW), TODAY)
    assert result.blocking == [] and len(result.allowed) == 1
    later = sa.evaluate(findings, sa.parse_allowlist(ALLOW), dt.date(2027, 1, 1))
    assert len(later.blocking) == 1, "the exception expired on 2026-12-31 and must stop applying"


def test_an_alias_on_the_allowlist_also_covers_the_finding():
    findings = sa.parse_pip_audit(VULNERABLE, "api/requirements.txt")
    entries = sa.parse_allowlist("CVE-2023-32681 2026-12-31 same advisory, CVE name")
    assert sa.evaluate(findings, entries, TODAY).blocking == []


def test_an_expired_allowlist_entry_is_reported_even_when_it_matches_nothing():
    result = sa.evaluate([], sa.parse_allowlist(ALLOW), TODAY)
    assert [e.advisory for e in result.expired] == ["GHSA-old-old-old"]


# --- the whole run, with the auditors stubbed ---------------------------------------------------------------------

def run(pip_out=CLEAN, npm_out=npm_json(), allow="", files=("api/requirements.txt",), pip_exc=None, npm_exc=None):
    def pip_runner(_path):
        if pip_exc:
            raise pip_exc
        return pip_out

    def npm_runner(_dir):
        if npm_exc:
            raise npm_exc
        return npm_out

    return sa.main([], pip_runner=pip_runner, npm_runner=npm_runner, today=TODAY, requirements=list(files),
                   allowlist_text=allow, npm_dir="csv-table-hub-main")


def test_a_clean_run_exits_zero(capsys):
    assert run() == 0
    assert "no known vulnerabilities" in capsys.readouterr().out


def test_a_vulnerable_python_dependency_exits_one_and_names_it(capsys):
    assert run(pip_out=VULNERABLE) == 1
    out = capsys.readouterr().out
    assert "requests 2.30.0" in out and "PYSEC-2023-74" in out and "2.31.0" in out


def test_a_high_npm_vulnerability_exits_one(capsys):
    assert run(npm_out=NPM_HIGH) == 1
    assert "lodash" in capsys.readouterr().out


def test_an_allowlisted_finding_exits_zero_and_says_it_was_allowed(capsys):
    assert run(pip_out=VULNERABLE, allow=ALLOW.replace("GHSA-old-old-old 2026-01-01  an exception that has expired", "")) == 0
    assert "allowed" in capsys.readouterr().out.lower()


def test_an_expired_allowlist_entry_alone_exits_one(capsys):
    assert run(allow=ALLOW) == 1
    assert "expired" in capsys.readouterr().out.lower()


@pytest.mark.parametrize("which", ["pip_exc", "npm_exc"])
def test_when_an_auditor_cannot_run_the_result_is_could_not_audit_not_a_pass(which, capsys):
    assert run(**{which: sa.AuditError("could not reach the advisory database")}) == 2
    assert "could not audit" in capsys.readouterr().out.lower()


def test_when_there_are_no_requirements_files_the_result_is_could_not_audit(capsys):
    assert run(files=()) == 2


# --- discovery ---------------------------------------------------------------------------------------------------

def test_every_tracked_requirements_file_is_audited():
    tracked = subprocess.run(["git", "ls-files", "*requirements*.txt"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.split()
    assert tracked, "expected at least one tracked requirements file"
    assert sorted(sa.discover_requirements(ROOT)) == sorted(tracked)
