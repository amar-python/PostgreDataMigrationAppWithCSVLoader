"""#335 (SE-14): CI checks every Terraform root, with pinned and verified tools, and cannot quietly stop doing it.

Before this, nothing ran `terraform fmt`, `validate`, tflint or checkov, so a typo or an insecure setting in
infra/ was found only when someone ran `terraform plan` by hand. These read the workflow and the script as text:

  * every directory under infra/ that holds .tf files is a root the script checks (found, not listed, so a new
    root cannot be missed);
  * the tool versions are pinned and each download is checked against its published SHA-256;
  * validate never touches the real state (`-backend=false`), and nothing ends in `|| true`;
  * checkov fails on any finding not in the reviewed baseline, so a new insecure setting fails the job while the
    existing findings wait for triage under #335.

No network and no Terraform needed: the job itself runs the tools.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "terraform.yml"
SCRIPT = ROOT / "scripts" / "terraform_check.sh"
BASELINE = ROOT / "infra" / ".checkov.baseline"
TFLINT = ROOT / "infra" / ".tflint.hcl"


def _roots() -> list[str]:
    return sorted({p.parent.relative_to(ROOT).as_posix() for p in (ROOT / "infra").rglob("*.tf")
                   if ".terraform" not in p.parts})


@pytest.fixture(scope="module")
def workflow() -> dict:
    assert WORKFLOW.exists(), f"{WORKFLOW.relative_to(ROOT)} is missing: nothing checks the Terraform"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def script() -> str:
    assert SCRIPT.exists(), f"{SCRIPT.relative_to(ROOT)} is missing"
    return SCRIPT.read_text(encoding="utf-8")


def test_there_are_terraform_roots_to_check():
    assert len(_roots()) >= 4, f"expected the dev, test, staging and prod roots, found {_roots()}"


def test_it_runs_on_every_pull_request_and_push_to_main(workflow):
    on = workflow.get(True) or workflow.get("on")  # PyYAML reads the bare key `on` as True
    assert "pull_request" in on and on["push"]["branches"] == ["main"]
    assert "paths" not in (on.get("pull_request") or {}), "a path filter leaves a required check pending forever"


def test_the_job_runs_the_script_and_nothing_else_decides_the_result(workflow):
    job = workflow["jobs"]["terraform"]
    runs = "\n".join(s.get("run", "") for s in job["steps"])
    assert "bash scripts/terraform_check.sh" in runs
    assert "|| true" not in runs and not job.get("continue-on-error")
    assert not any(s.get("continue-on-error") for s in job["steps"])


def test_the_tool_versions_are_pinned_and_every_download_is_verified(workflow):
    env = workflow["jobs"]["terraform"].get("env") or {}
    for key in ("TERRAFORM_VERSION", "TERRAFORM_SHA256", "TFLINT_VERSION", "TFLINT_SHA256", "CHECKOV_VERSION"):
        assert env.get(key), f"{key} is not set on the job"
    assert re.fullmatch(r"\d+\.\d+\.\d+", str(env["TERRAFORM_VERSION"]))
    assert re.fullmatch(r"[0-9a-f]{64}", env["TERRAFORM_SHA256"])
    assert re.fullmatch(r"[0-9a-f]{64}", env["TFLINT_SHA256"])
    runs = "\n".join(s.get("run", "") for s in workflow["jobs"]["terraform"]["steps"])
    assert runs.count("sha256sum -c") >= 2, "both downloads must be checked against their pinned SHA-256"
    assert re.search(r"pip install checkov==\$\{?CHECKOV_VERSION\}?", runs)


def test_the_script_finds_the_roots_rather_than_listing_them(script):
    for root in _roots():
        assert root not in script, f"{root} is hard-coded: find the roots so a new one cannot be missed"
    assert "find infra" in script and "*.tf" in script


def test_the_script_runs_every_check_and_never_touches_real_state(script):
    assert re.search(r"set -[a-z]*e[a-z]*u[a-z]*o pipefail|set -euo pipefail", script)
    assert "fmt -check -recursive" in script
    assert "init -backend=false" in script and "validate" in script
    assert "tflint" in script and "--config" in script
    assert "checkov" in script and "--baseline" in script
    assert "|| true" not in script


def test_tflint_uses_the_recommended_terraform_rules():
    text = TFLINT.read_text(encoding="utf-8")
    assert re.search(r'plugin\s+"terraform"', text) and re.search(r'preset\s*=\s*"recommended"', text)


def test_the_checkov_baseline_is_valid_and_names_only_real_files():
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    findings = data["failed_checks"]
    assert findings, "an empty baseline would hide the fact that the existing findings still need triage"
    for entry in findings:
        path = ROOT / "infra" / entry["file"].lstrip("/")
        assert path.exists(), f"baseline names {entry['file']}, which does not exist"
