"""#326 (SE-05), part 2: every image the bundle ships is scanned, an SBOM is written for it, and the bundle needs both.

Read as text (trivy and Docker are not available to a unit test). What they pin is how such a job usually goes quiet:

  * a scan that is not on both CPUs, or skips one of the three images;
  * `|| true`, `continue-on-error`, or a scanner version that floats (`latest`);
  * a `bundle` job that no longer waits for the scan, so a vulnerable bundle still ships;
  * an SBOM that is written but never reaches the bundle (the bundle job must require it);
  * an exception in .trivyignore.yaml with no reason or no expiry date, or one that has expired.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "container-bundle.yml"
IGNORE = ROOT / ".trivyignore.yaml"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def job(workflow: dict, name: str) -> dict:
    assert name in workflow["jobs"], f"container-bundle.yml has no '{name}' job"
    return workflow["jobs"][name]


def run_text(j: dict) -> str:
    return "\n".join(s.get("run", "") for s in j["steps"])


def test_the_scan_job_runs_on_both_cpus(workflow):
    matrix = job(workflow, "scan")["strategy"]["matrix"]["include"]
    assert {m["arch"] for m in matrix} == {"amd64", "arm64"}, "each CPU's images are different builds"


def test_the_scan_checks_all_three_images_and_fails_on_a_fixable_high_or_critical(workflow):
    text = run_text(job(workflow, "scan")).replace("\\\n", " ")
    assert re.search(r"for img in api frontend db", text), "the scan must loop over all three images"
    assert "--severity HIGH,CRITICAL" in text
    assert "--exit-code 1" in text, "a finding must fail the job"
    assert "--ignore-unfixed" in text, "fail on what can be fixed; an unfixed CVE has no action to take"
    assert ".trivyignore.yaml" in text, "the documented exceptions file must be the one trivy reads"


def test_trivy_is_pinned_to_a_version(workflow):
    text = run_text(job(workflow, "scan"))
    assert re.search(r"ghcr\.io/aquasecurity/trivy:\d+\.\d+\.\d+", text), "pin trivy to a version tag"
    assert "trivy:latest" not in text


def test_a_finding_cannot_pass_quietly(workflow):
    j = job(workflow, "scan")
    assert not j.get("continue-on-error")
    for step in j["steps"]:
        assert not step.get("continue-on-error"), step.get("name")
        assert "|| true" not in step.get("run", "") and "||true" not in step.get("run", ""), step.get("name")
    text = run_text(j)
    assert "exit" in text and "rc" in text, "a loop over three images must keep a failure from the first one"


def test_a_cyclonedx_sbom_is_written_for_every_image_and_kept_even_if_the_scan_fails(workflow):
    j = job(workflow, "scan")
    text = run_text(j)
    assert "--format cyclonedx" in text and "dist/sbom/te-" in text and ".cdx.json" in text
    uploads = [s for s in j["steps"] if "upload-artifact" in s.get("uses", "")]
    assert uploads and "te-sbom-" in uploads[0]["with"]["name"]
    assert uploads[0].get("if") == "always()", "the SBOM is the evidence for a failed scan too"


def test_the_bundle_waits_for_the_scan_and_requires_the_sboms(workflow):
    j = job(workflow, "bundle")
    needs = j["needs"] if isinstance(j["needs"], list) else [j["needs"]]
    assert {"images", "scan"} <= set(needs), "a vulnerable bundle must not be assembled"
    downloads = [s for s in j["steps"] if "download-artifact" in s.get("uses", "")]
    assert any("te-sbom-" in str(d.get("with", {}).get("pattern", "")) for d in downloads), "SBOMs must be downloaded"
    assemble = [s for s in j["steps"] if "assemble" in s.get("run", "")][0]
    assert str(assemble.get("env", {}).get("TE_REQUIRE_SBOM")) == "1"


def test_the_bundle_job_checks_that_the_sboms_are_in_the_archive(workflow):
    text = run_text(job(workflow, "bundle"))
    assert "tar -tzf" in text and "cdx" in text, "list the archive and look for the SBOMs in it"
    assert re.search(r"-eq 6\b", text), "require exactly 6 SBOMs (3 images x 2 CPUs), not 'at least one'"


@pytest.mark.parametrize("event", ["pull_request", "push"])
def test_a_change_to_the_exceptions_file_runs_the_workflow(workflow, event):
    on = workflow.get(True) or workflow.get("on")
    assert ".trivyignore.yaml" in on[event]["paths"]


def test_the_trivy_exceptions_file_documents_and_limits_every_exception():
    data = yaml.safe_load(IGNORE.read_text(encoding="utf-8")) or {}
    entries = data.get("vulnerabilities") or []
    for entry in entries:
        assert entry.get("id"), f"an exception without an id: {entry}"
        assert len(str(entry.get("statement", ""))) >= 15, f"{entry.get('id')}: say why it is accepted"
        expires = entry.get("expired_at")
        assert expires, f"{entry.get('id')}: an exception needs an expiry date"
        expires = expires if isinstance(expires, dt.date) else dt.date.fromisoformat(str(expires))
        assert expires >= dt.date.today(), f"{entry['id']} expired on {expires}: renew it with a new reason, or remove it"
