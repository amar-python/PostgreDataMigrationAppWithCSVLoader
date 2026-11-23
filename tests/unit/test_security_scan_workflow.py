"""#326 (SE-05): the security-scan workflow does what it says, and cannot quietly stop doing it.

A scanner is worth having only if a finding fails the build and the scan covers what it claims to. These read the
workflow and the gitleaks config as text, and pin the ways such a job usually goes quiet:

  * the checkout is shallow, so "scan the history" scans one commit;
  * the scan step ends in `|| true` or the job has `continue-on-error`;
  * the scanner image is `latest` (or unpinned), so what runs changes without a commit here;
  * the gitleaks config does not extend the default rules, which leaves only the custom ones (usually none);
  * the allow-list file is malformed or holds an expired entry, which would only show up on the weekly run.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest
import yaml

from scripts import security_audit as sa

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "security-scan.yml"
GITLEAKS = ROOT / ".gitleaks.toml"
ALLOWLIST = ROOT / "security" / "audit-allowlist.txt"


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.exists(), f"{WORKFLOW} is missing"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def steps(workflow: dict, job: str) -> list[dict]:
    return workflow["jobs"][job]["steps"]


def run_text(workflow: dict, job: str) -> str:
    return "\n".join(s.get("run", "") for s in steps(workflow, job))


def test_it_runs_on_pull_requests_pushes_to_main_weekly_and_on_demand(workflow):
    on = workflow.get(True) or workflow.get("on")  # PyYAML reads the bare key `on` as the boolean True
    assert "pull_request" in on and "workflow_dispatch" in on
    assert on["push"]["branches"] == ["main"]
    assert on["schedule"], "new advisories appear without a code change, so it must also run on a schedule"


def test_the_token_can_only_read(workflow):
    assert workflow["permissions"] == {"contents": "read"}


@pytest.mark.parametrize("job", ["dependency-audit", "secret-scan"])
def test_no_job_or_step_can_fail_without_failing_the_build(workflow, job):
    assert not workflow["jobs"][job].get("continue-on-error"), f"{job} has continue-on-error"
    for step in steps(workflow, job):
        assert not step.get("continue-on-error"), f"step {step.get('name')} has continue-on-error"
        assert "|| true" not in step.get("run", "") and "||true" not in step.get("run", ""), step.get("name")


def test_the_dependency_audit_installs_a_pinned_pip_audit_and_runs_the_script(workflow):
    text = run_text(workflow, "dependency-audit")
    assert re.search(r"pip install pip-audit==\d+\.\d+\.\d+", text), "pip-audit must be pinned to a version"
    assert "scripts/security_audit.py" in text


def test_the_secret_scan_checks_out_the_whole_history(workflow):
    checkout = [s for s in steps(workflow, "secret-scan") if "checkout" in s.get("uses", "")]
    assert checkout and checkout[0].get("with", {}).get("fetch-depth") == 0, (
        "a shallow checkout makes the 'full history' scan look at one commit")


def test_the_secret_scan_runs_a_pinned_gitleaks_that_fails_on_a_leak(workflow):
    text = run_text(workflow, "secret-scan")
    assert re.search(r"ghcr\.io/gitleaks/gitleaks:v\d+\.\d+\.\d+", text), "pin gitleaks to a version tag, not latest"
    assert "latest" not in text
    assert " git " in text and "--exit-code 1" in text
    assert "--redact" in text, "a finding must not print the secret into a public log"


def test_the_secret_scan_proves_it_can_still_detect_a_secret(workflow):
    """'no leaks found' is also what a scanner with broken rules says. A canary, a known fake secret written at run
    time, must be flagged on every run, or the job fails."""
    canary = [s for s in steps(workflow, "secret-scan") if "canary" in s.get("name", "").lower()]
    assert canary, "the secret-scan job has no canary step"
    run = canary[0]["run"]
    assert "gitleaks" in run and " dir " in run, "the canary must run gitleaks on the fake secret"
    assert re.search(r"if\s+docker run", run), "the canary must pass only when gitleaks FAILS (found the secret)"
    assert "exit 1" in run


def test_the_canary_token_is_never_written_out_whole_in_the_repository():
    """Written whole, the fake key would be a finding in the history of the repository it is meant to protect."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"AKIA[A-Z2-7]{16}", text), "the canary AWS key appears whole in the workflow file"


def test_the_gitleaks_config_keeps_the_default_rules():
    assert GITLEAKS.exists(), ".gitleaks.toml is missing"
    text = GITLEAKS.read_text(encoding="utf-8")
    assert re.search(r"(?m)^\[extend\]\s*\n\s*useDefault\s*=\s*true", text), (
        "a config without [extend] useDefault = true replaces gitleaks's rules with only the ones written here")


def test_every_allowlisted_secret_has_a_reason():
    text = GITLEAKS.read_text(encoding="utf-8")
    # Each [[allowlists]] block (or the older [allowlist]) must carry a description saying why.
    blocks = re.split(r"(?m)^\[\[?allowlists?\]\]?\s*$", text)[1:]
    for block in blocks:
        assert re.search(r"(?m)^\s*description\s*=\s*\"[^\"]{15,}\"", block), (
            "every gitleaks allow-list block needs a description of why it is safe")


def test_the_real_audit_allowlist_parses_and_holds_no_expired_entry():
    entries = sa.parse_allowlist(ALLOWLIST.read_text(encoding="utf-8"))
    expired = [e.advisory for e in entries if e.expires < dt.date.today()]
    assert expired == [], f"expired exceptions in security/audit-allowlist.txt: {expired}"
