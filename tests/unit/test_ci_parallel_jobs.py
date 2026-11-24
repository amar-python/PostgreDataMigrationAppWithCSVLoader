"""CI speed-up: the quality-gate workflow's parallel layout, the docs-only skip, and the gate that ties them together.

The integration job took 25 to 40 minutes because it ran in series: the whole suite, then the system tests again with
the egress block, then the whole suite a third time for coverage. Now (workflow ``quality-gate.yml``):

  changes ──► integration-shards (3 in parallel, each with its own PostgreSQL)
          ├─► integration-egress (the firewall steps and the egress-blocked pass)
          ├─► coverage           (the coverage gate)
          └─► integration-postgres  the check that is still called "integration (postgres service)": it succeeds only
                                    if every one of those succeeded (or all were skipped for a docs-only change).

Asserted here, with no network and no database:
  * ``scripts/ci_changes.py`` skips the database jobs only for a change that is only documentation that nothing reads
    (a doc named in a test, eval, script or workflow can break them, so it counts as code); on any doubt it runs them;
  * ``scripts/ci_gate.py`` turns the jobs' results into one pass or fail, and a skipped job never passes a code change;
  * the workflow has these jobs, each heavy job its own PostgreSQL, the shards cover every file, the coverage step and
    the egress steps are intact, the check keeps its name, a push to ``main`` always runs everything, and a newer push
    to a pull request cancels the older run.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gate.yml"

sys.path.insert(0, str(ROOT / "scripts"))
try:
    import ci_changes  # noqa: E402
    import ci_gate  # noqa: E402
    import ci_shards  # noqa: E402
finally:
    sys.path.pop(0)


# -- scripts/ci_changes.py: when may the database jobs be skipped? -----------------------------------------------------

@pytest.fixture
def tree(tmp_path):
    """A small repository: docs nothing reads, a doc a test reads, a doc a workflow names, code."""
    files = {
        "docs/audit/example_report.md": "# report\n",
        "docs/NOTES_EXAMPLE.md": "# notes\n",
        "docs/ROLES.md": "# roles\n",
        "docs/WORKFLOW_ONLY.md": "# named by a workflow\n",
        "DECISIONS/2026-11-23-x.md": "# decision\n",
        "README.md": "# readme\n",
        "tests/system/test_roles.py": 'DOC = root / "docs" / "ROLES.md"\n',
        ".github/workflows/x.yml": "run: cat docs/WORKFLOW_ONLY.md\n",
        "api/main.py": "x = 1\n",
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def test_a_change_to_documents_nothing_reads_skips_the_database_jobs(tree):
    assert ci_changes.is_docs_only(["docs/audit/example_report.md"], tree) is True
    assert ci_changes.is_docs_only(["docs/audit/example_report.md", "DECISIONS/2026-11-23-x.md", "docs/NOTES_EXAMPLE.md"], tree) is True


def test_code_always_runs_everything(tree):
    for path in ("api/main.py", "scripts/x.sh", "requirements-dev.txt", ".github/workflows/quality-gate.yml",
                 "tests/unit/test_x.py", "csv-table-hub-main/src/a.ts", "Makefile"):
        assert ci_changes.is_docs_only([path], tree) is False, path


def test_one_code_file_among_documents_runs_everything(tree):
    assert ci_changes.is_docs_only(["docs/NOTES_EXAMPLE.md", "api/main.py"], tree) is False


def test_a_document_a_test_reads_counts_as_code(tree):
    """tests/system/test_roles.py reads docs/ROLES.md; skipping the database job could hide a break."""
    assert ci_changes.is_docs_only(["docs/ROLES.md"], tree) is False


def test_a_document_a_workflow_names_counts_as_code(tree):
    assert ci_changes.is_docs_only(["docs/WORKFLOW_ONLY.md"], tree) is False


def test_a_document_only_other_documents_mention_does_not_count_as_read(tree):
    (tree / "docs" / "OTHER.md").write_text("see NOTES_EXAMPLE.md and audit/example_report.md\n")
    assert ci_changes.is_docs_only(["docs/NOTES_EXAMPLE.md"], tree) is True


def test_the_root_readme_is_documentation_but_a_test_that_names_it_makes_it_code(tree):
    assert ci_changes.is_docs_only(["README.md"], tree) is True
    (tree / "tests" / "unit").mkdir(parents=True)
    (tree / "tests" / "unit" / "test_readme.py").write_text('open("README.md")\n')
    assert ci_changes.is_docs_only(["README.md"], tree) is False


def test_no_changed_files_means_run_everything(tree):
    """An empty or unreadable diff is not evidence that nothing needs testing."""
    assert ci_changes.is_docs_only([], tree) is False


def test_a_deleted_or_renamed_document_nothing_reads_is_still_documentation(tree):
    assert ci_changes.is_docs_only(["docs/gone.md"], tree) is True


def test_a_push_always_runs_everything(tree):
    assert ci_changes.decide("push", ["docs/NOTES_EXAMPLE.md"], tree) == "true"


def test_a_pull_request_decides_by_its_files(tree):
    assert ci_changes.decide("pull_request", ["docs/NOTES_EXAMPLE.md"], tree) == "false"
    assert ci_changes.decide("pull_request", ["docs/NOTES_EXAMPLE.md", "api/main.py"], tree) == "true"


def test_any_other_event_or_no_files_runs_everything(tree):
    assert ci_changes.decide("workflow_dispatch", ["docs/NOTES_EXAMPLE.md"], tree) == "true"
    assert ci_changes.decide("pull_request", [], tree) == "true"
    assert ci_changes.decide("pull_request", None, tree) == "true", "a failed git diff must not skip the tests"


def test_the_real_repository_runs_everything_for_its_own_ci_files():
    for path in ("scripts/ci_changes.py", "scripts/ci_gate.py", "scripts/ci_shards.py", "ci/shard_weights.json",
                 ".github/workflows/quality-gate.yml"):
        assert ci_changes.is_docs_only([path], ROOT) is False, path


def test_the_real_documents_the_tests_read_are_not_skippable():
    for path in ("docs/ROLES.md", "docs/API_INTEGRATION.md", "docs/SECURITY_REVIEW_PACK.md"):
        assert (ROOT / path).is_file(), path
        assert ci_changes.is_docs_only([path], ROOT) is False, f"{path} is read by a test"


# -- scripts/ci_gate.py: one verdict from the jobs' results -------------------------------------------------------------

def gate(changed: str, **results: str) -> int:
    return ci_gate.verdict(changed, results)[0]


def test_a_code_change_passes_only_if_every_job_succeeded():
    assert gate("true", shards="success", egress="success", coverage="success") == 0


@pytest.mark.parametrize("bad", ["failure", "cancelled", "skipped"])
def test_a_code_change_fails_if_any_job_did_not_succeed(bad):
    for broken in ("shards", "egress", "coverage"):
        results = {"shards": "success", "egress": "success", "coverage": "success", broken: bad}
        assert gate("true", **results) == 1, (broken, bad)


def test_a_skipped_job_never_passes_a_code_change():
    """The failure this guards: the jobs are skipped by mistake, the gate sees nothing red, and a change merges untested."""
    assert gate("true", shards="skipped", egress="skipped", coverage="skipped") == 1


def test_a_documentation_only_change_passes_when_the_jobs_were_skipped():
    assert gate("false", shards="skipped", egress="skipped", coverage="skipped") == 0


def test_a_documentation_only_change_still_fails_if_a_job_that_ran_failed():
    assert gate("false", shards="failure", egress="skipped", coverage="skipped") == 1
    assert gate("false", shards="success", egress="cancelled", coverage="skipped") == 1


@pytest.mark.parametrize("changed", ["", "maybe", "True", "none"])
def test_an_unknown_answer_from_the_changes_job_fails(changed):
    """If the changes job itself failed its output is empty: that must not read as 'skip everything'."""
    assert gate(changed, shards="skipped", egress="skipped", coverage="skipped") == 1
    assert gate(changed, shards="success", egress="success", coverage="success") == 1


def test_no_results_at_all_fails():
    assert ci_gate.verdict("true", {})[0] == 1


def test_the_message_names_every_job_and_what_happened():
    code, message = ci_gate.verdict("true", {"shards": "success", "coverage": "failure"})
    assert code == 1 and "shards" in message and "coverage" in message and "failure" in message


def test_the_cli_exits_with_the_verdict():
    ok = subprocess.run([sys.executable, str(ROOT / "scripts" / "ci_gate.py"), "true", "shards=success", "coverage=success"],
                        capture_output=True, text=True)
    bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "ci_gate.py"), "true", "shards=success", "coverage=failure"],
                         capture_output=True, text=True)
    assert (ok.returncode, bad.returncode) == (0, 1), (ok.stdout, bad.stdout)


# -- the workflow --------------------------------------------------------------------------------------------------------

def load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def jobs() -> dict:
    return load()["jobs"]


def run_text(job: dict) -> str:
    return "\n".join((s.get("run") or "") for s in job.get("steps", []))


HEAVY = ("integration-shards", "integration-egress", "coverage")


def test_the_parallel_jobs_exist_and_the_check_keeps_its_name():
    j = jobs()
    for job_id in ("changes", "free-tier", *HEAVY, "integration-postgres", "accessibility", "browser"):
        assert job_id in j, job_id
    assert j["integration-postgres"]["name"] == "integration (postgres service)", (
        "the aggregate check keeps the name the owner's branch protection would require")


def test_the_heavy_jobs_wait_for_the_changes_job_and_skip_for_documentation_only():
    for job_id in HEAVY:
        job = jobs()[job_id]
        assert "changes" in (job["needs"] if isinstance(job["needs"], list) else [job["needs"]]), job_id
        assert "needs.changes.outputs.code == 'true'" in str(job.get("if")), job_id


def test_the_fast_jobs_always_run():
    for job_id in ("free-tier", "accessibility", "browser"):
        job = jobs()[job_id]
        assert "if" not in job, f"{job_id} must run on every change (the free tier is the docs-consistency tests)"
        assert "needs" not in job, f"{job_id} must not wait for anything"


def test_the_changes_job_asks_the_script_and_exposes_the_answer():
    job = jobs()["changes"]
    assert job["outputs"]["code"], "the job must expose `code`"
    text = run_text(job)
    assert "scripts/ci_changes.py" in text
    checkout = next(s for s in job["steps"] if "checkout" in (s.get("uses") or ""))
    assert (checkout.get("with") or {}).get("fetch-depth") in (0, "0"), "the diff against the base needs its history"
    assert "pip install" not in text and "pytest" not in text, "the changes job only decides"


def test_a_push_to_main_never_skips():
    """ci_changes.decide('push', ...) is 'true'; the workflow must pass the event name through."""
    assert "github.event_name" in run_text(jobs()["changes"])


def test_the_shards_cover_every_file_and_cannot_drift_from_the_script():
    job = jobs()["integration-shards"]
    matrix = job["strategy"]["matrix"]["shard"]
    assert matrix == list(range(1, ci_shards.SHARDS + 1)), "the matrix must be 1..SHARDS of scripts/ci_shards.py"
    assert job["strategy"].get("fail-fast") is False, "one red shard must not hide what the others found"
    text = run_text(job)
    assert "ci_shards.py files --shard ${{ matrix.shard }}" in text
    assert f"--of {ci_shards.SHARDS}" in text
    assert "scripts/test_report.py" in text and "--strict" in text and "--paths" in text
    assert '--markers "not accessibility"' in text


def test_every_database_job_has_its_own_postgres_and_the_same_setup_as_before():
    for job_id in ("integration-shards", "integration-egress"):
        job = jobs()[job_id]
        service = job["services"]["postgres"]
        assert service["image"].startswith("postgres:16"), job_id
        text = run_text(job)
        for needed in ("pip install", "build/config.local.env", "evals/runner.py --tiers p,i,s,e", "deploy_all.sh"):
            assert needed in text, f"{job_id} lost the setup step that runs {needed!r}"


def _shard_step(job_id: str = "integration-shards") -> dict:
    return next(s for s in jobs()[job_id]["steps"] if "test_report.py" in (s.get("run") or ""))


def test_each_shard_measures_coverage_and_hands_its_data_to_the_coverage_job():
    """Coverage is no longer a third run of the whole suite: every shard records it as it runs, the coverage job combines."""
    job = jobs()["integration-shards"]
    step = _shard_step()
    opts = (step.get("env") or {}).get("PYTEST_ADDOPTS", "")
    for scope in ("api", "streamlit_app", "build/csv", "evals"):
        assert f"--cov={scope}" in opts, scope
    assert "--cov-branch" in opts and "--cov-report=" in opts
    assert "coverage-shard-${{ matrix.shard }}.dat" in step["run"] or any(
        "coverage-shard-${{ matrix.shard }}.dat" in (s.get("run") or "") for s in job["steps"])
    uploads = [s for s in job["steps"] if "upload-artifact" in (s.get("uses") or "") and
               "coverage-shard-${{ matrix.shard }}" in str((s.get("with") or {}).get("name", ""))]
    assert len(uploads) == 1, "each shard uploads its own coverage data under a name that is unique per shard"
    assert "coverage-shard-${{ matrix.shard }}.dat" in str(uploads[0]["with"]["path"])


def test_the_coverage_job_combines_the_shards_and_applies_the_floors_and_needs_no_database():
    job = jobs()["coverage"]
    assert "services" not in job, "combining data files needs no database"
    needs = job["needs"]
    assert {"changes", "integration-shards"} <= set(needs)
    assert "needs.changes.outputs.code == 'true'" in str(job.get("if"))
    assert "needs.integration-shards.result == 'success'" in str(job.get("if")), (
        "no coverage verdict from a run in which a shard failed")
    download = next(s for s in job["steps"] if "download-artifact" in (s.get("uses") or ""))
    assert "coverage-shard-*" in str(download["with"].get("pattern"))
    assert download["with"].get("merge-multiple") in (True, "true")
    run = run_text(job)
    assert "coverage combine" in run and "coverage json" in run
    assert "check_coverage_floors.py coverage.json" in run
    assert "set -o pipefail" in run or "set -e" in run or "check_coverage_floors.py" in run
    assert not any("pytest" in (s.get("run") or "") for s in job["steps"]), "the coverage job runs no tests"


def test_the_egress_pass_is_sharded_and_keeps_its_firewall_steps():
    job = jobs()["integration-egress"]
    assert job["strategy"]["matrix"]["shard"] == list(range(1, ci_shards.EGRESS_SHARDS + 1))
    assert job["strategy"].get("fail-fast") is False
    text = run_text(job)
    for needed in ("egress_firewall.sh install egresstest", "egress_firewall.sh check", "--block-egress",
                   "egress_firewall.sh remove"):
        assert needed in text, needed
    assert "test_report.py" not in text, "the egress job does not re-run the whole suite on the open network"
    assert "ci_shards.py files --shard ${{ matrix.shard }}" in text
    assert f"--of {ci_shards.EGRESS_SHARDS}" in text and "--only tests/system/" in text
    uploads = [s for s in job["steps"] if "upload-artifact" in (s.get("uses") or "")]
    assert uploads and all("${{ matrix.shard }}" in str(s["with"]["name"]) for s in uploads), (
        "artifact names must be unique per shard or the uploads collide")


def test_the_egress_shards_hold_every_system_test_file_once():
    files = ci_shards.test_files(only="tests/system/")
    shards = ci_shards.assign(files, ci_shards.load_weights(), ci_shards.EGRESS_SHARDS)
    flat = [f for sh in shards for f in sh]
    assert sorted(flat) == sorted(files) and all(shards)


def test_the_gate_job_runs_always_and_asks_the_script():
    job = jobs()["integration-postgres"]
    assert str(job["if"]).strip() == "always()", "a skipped or failed needed job must still produce a verdict"
    needs = job["needs"]
    assert {"changes", *HEAVY} <= set(needs)
    text = run_text(job)
    assert "scripts/ci_gate.py" in text
    for job_id in HEAVY:
        assert f"needs.{job_id}.result" in text, job_id
    assert "needs.changes.outputs.code" in text
    assert "services" not in job, "the gate does not need a database"
    assert "pytest" not in text and "pip install" not in text


def test_a_newer_push_to_a_pull_request_cancels_the_older_run_but_main_is_never_cancelled():
    concurrency = load()["concurrency"]
    assert "github.ref" in concurrency["group"] or "github.head_ref" in concurrency["group"]
    assert "pull_request" in str(concurrency["cancel-in-progress"]), "only pull_request runs may be cancelled"
    assert "push" not in str(concurrency["cancel-in-progress"]).replace("pull_request", "")


def test_the_triggers_are_unchanged_and_nothing_is_skipped_by_path_at_the_workflow_level():
    wf = load()
    on = wf.get("on") if "on" in wf else wf[True]
    assert set(on) == {"push", "pull_request"}
    assert "paths-ignore" not in str(on) and "paths" not in (on.get("pull_request") or {}), (
        "a workflow-level path filter would leave the required check pending forever; the changes job decides instead")
    assert on["push"]["branches"] == ["main", "master"]


# -- the sample documents must not be real ones -------------------------------------------------------------------------

def test_the_sample_documents_in_the_fixture_are_not_real_documents_of_this_repository(tree):
    """A test file naming a real document makes that document count as 'read by a test', so a change to it could never
    skip the database jobs (found the first time the real audit report was changed on its own). The fixture's documents
    that stand for 'nothing reads this' must therefore have names no real file has."""
    real_root = Path(__file__).resolve().parents[2]
    for rel in ("docs/audit/example_report.md", "docs/NOTES_EXAMPLE.md"):
        assert (tree / rel).is_file(), f"the fixture lost its sample document {rel}"
        assert not (real_root / rel).exists(), f"{rel} is a real file now: pick another sample name"
    # The real report's name is built, not written, so that this very file does not name it (that would defeat the point).
    real_report = "2026" + "1123.md"
    assert not (tree / "docs" / "audit" / real_report).exists(), "the fixture must not use the real report's name"
    assert not (tree / "docs" / ("NOTES" + ".md")).exists()
    assert (real_root / "docs" / "audit" / real_report).is_file(), "the real report this guard protects was renamed: update it"
