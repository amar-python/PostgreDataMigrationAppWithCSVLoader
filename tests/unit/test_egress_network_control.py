"""#310 (OIT-029, BR-37): how the network-level egress check is wired into the tests and CI.

``tests/system/test_egress_network_blocked.py`` is the negative control for the firewall block
(``scripts/egress_firewall.sh``); it would connect on an open network, so it must never run there. And the CI job must
run things in an order that makes the check mean something. No firewall, no network, no database here: the wiring is
asserted by running pytest's collection and by reading the workflow. Asserted:

  * the control is left out of collection unless ``EGRESS_NETWORK_BLOCKED=1`` (so the strict full-suite run, the
    coverage run and a developer's ``pytest`` never run it), and is collected when it is set; its marker is registered;
  * in the egress job (its own job, in parallel with the test shards and the coverage gate): a dedicated user is created,
    the block is installed for that user, the control runs as that user and must have been counted (so the counter is proved to work),
    the count is zeroed, the egress-blocked tests run as that user, the count must be zero, and the block is removed
    in a step that runs even when an earlier step failed; the block is never installed for the runner's own user; the
    suite on the open network runs in the shards, never in this job;
  * the docs say the child-process and libpq gap is closed in CI, and how.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gate.yml"
CONTROL = "tests/system/test_egress_network_blocked.py"


# -- collection ------------------------------------------------------------------------------------------------------

def collected(extra_env: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "EGRESS_NETWORK_BLOCKED"} | extra_env
    return subprocess.run([sys.executable, "-m", "pytest", CONTROL, "--collect-only", "-q", "-p", "no:cacheprovider"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


def test_the_control_is_left_out_of_every_run_without_the_firewall():
    done = collected({})
    assert "test_egress_network_blocked.py::" not in done.stdout, done.stdout
    assert done.returncode == 5, f"nothing should be collected (pytest exit 5), got {done.returncode}:\n{done.stdout}"


def test_the_control_is_collected_when_the_firewall_is_up():
    done = collected({"EGRESS_NETWORK_BLOCKED": "1"})
    assert done.returncode == 0, done.stdout + done.stderr
    count = re.search(r"test_egress_network_blocked\.py: (\d+)", done.stdout)
    assert count and int(count.group(1)) >= 3, done.stdout


def test_the_marker_is_registered():
    ini = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert re.search(r"(?m)^\s+egress_network:", ini), "pytest.ini must register egress_network (--strict-markers)"


# -- the workflow ----------------------------------------------------------------------------------------------------

def job_steps() -> list[dict]:
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    return next(job["steps"] for job in jobs.values()
                if any("API tests with network egress blocked" in (s.get("name") or "") for s in job["steps"]))


def index_of(steps: list[dict], needle: str) -> int:
    for i, step in enumerate(steps):
        if needle in (step.get("run") or "") or needle in (step.get("name") or ""):
            return i
    raise AssertionError(f"no step mentions {needle!r}")


def test_the_block_is_installed_for_a_dedicated_user_never_the_runners():
    steps = job_steps()
    text = "\n".join(s.get("run") or "" for s in steps)
    assert re.search(r"useradd[^\n]*\begresstest\b", text), "a dedicated user must be created"
    assert re.search(r"egress_firewall\.sh install egresstest\b", text)
    assert not re.search(r"egress_firewall\.sh install\s+(runner|\$USER|\"\$USER\"|root|\$\(whoami\))", text), \
        "blocking the runner's user would cut off the agent that reports the job"


def test_the_steps_run_in_an_order_that_makes_the_check_mean_something():
    steps = job_steps()
    create = index_of(steps, "useradd")
    install = index_of(steps, "egress_firewall.sh install")
    control = index_of(steps, CONTROL)
    blocked_tests = index_of(steps, "--block-egress")
    check = index_of(steps, "egress_firewall.sh check")
    remove = index_of(steps, "egress_firewall.sh remove")
    assert create < install < control < blocked_tests < check < remove, (
        create, install, control, blocked_tests, check, remove)


def test_the_suite_on_the_open_network_runs_in_the_shards_never_with_the_control_enabled():
    jobs = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]
    shard_steps = jobs["integration-shards"]["steps"]
    text = "\n".join(str(s.get("env") or {}) + (s.get("run") or "") for s in shard_steps)
    assert "EGRESS_NETWORK_BLOCKED" not in text, "on an open network the control would connect"
    assert "test_report.py" in text, "the suite on the open network runs in the shards"
    assert "test_report.py" not in "\n".join(s.get("run") or "" for s in job_steps()), (
        "the egress job does not run the whole suite a second time")


def test_the_control_runs_as_the_blocked_user_and_must_have_been_counted_then_the_count_is_zeroed():
    steps = job_steps()
    step = steps[index_of(steps, CONTROL)]
    run = step["run"]
    assert "egress_firewall.sh run egresstest" in run, "the control must run as the blocked user"
    assert str((step.get("env") or {}).get("EGRESS_NETWORK_BLOCKED")) == "1"
    assert re.search(r"egress_firewall\.sh count", run) and re.search(r"-ge 1|-gt 0", run), \
        "the step must fail if the control's deliberate attempts were not counted (the counter would then prove nothing)"
    assert run.index("count") < run.index("egress_firewall.sh reset"), "zero the count after reading it"


def test_the_egress_blocked_tests_run_as_the_blocked_user_without_the_control():
    steps = job_steps()
    step = steps[index_of(steps, "--block-egress")]
    assert "egress_firewall.sh run egresstest" in step["run"]
    assert "EGRESS_NETWORK_BLOCKED" not in str(step.get("env") or {}), (
        "the deliberate attempts of the control must not run in the step whose count must stay zero")


def test_no_step_relies_on_sudo_preserving_the_environment():
    """sudo-rs (the default sudo on newer Ubuntu) ignores -E, so the variables never reached the blocked user (first CI run)."""
    for step in job_steps():
        run = step.get("run") or ""
        assert not re.search(r"sudo\s+(-\w*E\b|--preserve-env)", run), f"{step.get('name')}: pass the variables with `sudo env VAR=...`"


def test_the_variables_the_tests_need_are_passed_to_the_blocked_user_by_name():
    steps = job_steps()
    control = steps[index_of(steps, CONTROL)]["run"]
    blocked = steps[index_of(steps, "--block-egress")]["run"]
    for name, run in (("control", control), ("egress tests", blocked)):
        for needed in ('"PATH=$PATH"', '"PGHOST=$PGHOST"', '"PGPORT=$PGPORT"', '"PGUSER=$PGUSER"', '"PGPASSWORD=$PGPASSWORD"',
                       '"PGDATABASE=$PGDATABASE"'):
            assert needed in run, f"the {name} step must pass {needed} to the blocked user"
    assert '"EGRESS_NETWORK_BLOCKED=$EGRESS_NETWORK_BLOCKED"' in control, (
        "without it the control is deselected and pytest exits 5 (the first CI run)")
    assert '"EGRESS_NETWORK_BLOCKED=' not in blocked, "the control's variable must not reach the counted step"


def test_the_block_is_removed_even_when_an_earlier_step_failed():
    steps = job_steps()
    step = steps[index_of(steps, "egress_firewall.sh remove")]
    assert str(step.get("if")).strip() == "always()", step


# -- the docs --------------------------------------------------------------------------------------------------------

def test_the_docs_say_the_child_process_gap_is_closed_in_ci_and_how():
    sovereignty = (ROOT / "docs" / "SOVEREIGNTY.md").read_text(encoding="utf-8")
    assert "scripts/egress_firewall.sh" in sovereignty
    assert "child process" in sovereignty.lower() and "libpq" in sovereignty.lower()
    vcrm = (ROOT / "docs" / "VCRM.md").read_text(encoding="utf-8")
    row = next(line for line in vcrm.splitlines() if line.startswith("| BR-37 | ⚠️ Partial"))
    assert "egress_firewall.sh" in row, "the BR-37 evidence row should name the network-level check"
