"""CI quality gate structure tests — verify workflow correctness offline.

Validates that quality-gate.yml has the expected jobs, steps, and
configuration. Catches accidental removals or misconfigurations before
they reach CI. No database or network required.
"""
import re
import sys
import unittest
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gate.yml"
GAP_ANALYSIS = ROOT / "docs/GAP_ANALYSIS.md"


def _load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


class TestQualityGateStructure(unittest.TestCase):
    """quality-gate.yml must define all three expected jobs."""

    @classmethod
    def setUpClass(cls):
        if not WORKFLOW.exists():
            raise AssertionError(f"Workflow file not found: {WORKFLOW}")
        cls.wf = _load_workflow()
        cls.jobs = cls.wf.get("jobs", {})

    def test_has_free_tier_job(self):
        self.assertIn("free-tier", self.jobs)

    def test_has_integration_postgres_job(self):
        self.assertIn("integration-postgres", self.jobs)

    def test_triggers_on_pull_request(self):
        # PyYAML parses the YAML key `on` as boolean True
        triggers = self.wf.get(True, self.wf.get("on", {}))
        self.assertIn("pull_request", triggers)

    def test_triggers_on_push_to_main(self):
        triggers = self.wf.get(True, self.wf.get("on", {}))
        push_branches = triggers.get("push", {}).get("branches", [])
        self.assertIn("main", push_branches)


class TestAllJobsHaveConsistentStructure(unittest.TestCase):
    """All jobs must have checkout, python setup, and artifact upload."""

    @classmethod
    def setUpClass(cls):
        if not WORKFLOW.exists():
            raise AssertionError(f"Workflow file not found: {WORKFLOW}")
        cls.jobs = _load_workflow().get("jobs", {})

    def _step_names(self, job_id: str) -> list[str]:
        return [s.get("name", "") for s in self.jobs[job_id].get("steps", [])]

    def test_all_jobs_have_checkout(self):
        for job_id in self.jobs:
            names = self._step_names(job_id)
            self.assertTrue(
                any("Checkout" in n for n in names),
                f"Job {job_id!r} missing Checkout step",
            )

    def test_all_jobs_have_python_setup(self):
        for job_id in self.jobs:
            names = self._step_names(job_id)
            self.assertTrue(
                any("Setup Python" in n or "Python" in n for n in names),
                f"Job {job_id!r} missing Python setup step",
            )

    def test_all_jobs_have_artifact_upload(self):
        for job_id in self.jobs:
            names = self._step_names(job_id)
            self.assertTrue(
                any("Upload" in n for n in names),
                f"Job {job_id!r} missing artifact upload step",
            )

    def test_all_jobs_install_dev_deps(self):
        for job_id in self.jobs:
            names = self._step_names(job_id)
            self.assertTrue(
                any("Install" in n and "dep" in n.lower() for n in names),
                f"Job {job_id!r} missing install dev dependencies step",
            )


class TestAccessibilityJob(unittest.TestCase):
    """#168: the accessibility scans have their own job, and no other job collects them."""

    @classmethod
    def setUpClass(cls):
        cls.jobs = _load_workflow().get("jobs", {})

    def _run_text(self, job_id: str) -> str:
        return "\n".join(s.get("run", "") for s in self.jobs[job_id].get("steps", []))

    def test_has_accessibility_job_that_runs_only_the_accessibility_marker(self):
        self.assertIn("accessibility", self.jobs)
        self.assertIn('--markers accessibility', self._run_text("accessibility"))

    def test_accessibility_job_installs_a_browser_and_the_frontend(self):
        text = self._run_text("accessibility")
        self.assertIn("playwright install", text)
        self.assertIn("npm ci", text)
        self.assertIn("requirements-a11y.txt", text)

    def test_integration_job_excludes_accessibility_everywhere_it_runs_the_whole_tree(self):
        text = self._run_text("integration-postgres")
        self.assertIn('--markers "not accessibility"', text)
        self.assertIn('pytest tests/ -m "not accessibility"', text)

    def test_free_tier_markers_cannot_select_accessibility_tests(self):
        text = self._run_text("free-tier")
        self.assertNotIn("accessibility", text.split("--markers", 1)[1].splitlines()[0])


class TestGapAnalysisG2Accepted(unittest.TestCase):
    """G2 is accepted as out-of-scope, not closed.
    Checks the decision is recorded in docs/GAP_ANALYSIS.md.
    """
    @classmethod
    def setUpClass(cls):
        if not GAP_ANALYSIS.exists():
            raise AssertionError(f"docs/GAP_ANALYSIS.md not found: {GAP_ANALYSIS}")
        cls.content = GAP_ANALYSIS.read_text(encoding="utf-8")

    def test_g2_row_exists(self):
        found = any("| G2 |" in line for line in self.content.splitlines())
        self.assertTrue(found, "G2 row not found in docs/GAP_ANALYSIS.md")

    def test_g2_is_accepted_or_deferred(self):
        for line in self.content.splitlines():
            if "| G2 |" in line:
                lower = line.lower()
                self.assertTrue(
                    "accept" in lower or "defer" in lower,
                    f"G2 row should be accepted/deferred, got: {line.strip()}"
                )
                return
        self.fail("G2 row not found in docs/GAP_ANALYSIS.md")

    def test_g2_section_exists(self):
        self.assertIn("### G2", self.content)

    def test_g2_is_not_marked_closed(self):
        self.assertNotIn(
            "G2 — Windows CI cannot host PostgreSQL (Closed)",
            self.content,
            "G2 should not say Closed — it is Accepted"
        )


class TestPipedPytestKeepsItsExitStatus(unittest.TestCase):
    """#275: `pytest ... | tail` takes `tail`'s exit status, so a failing run can pass the step.

    GitHub runs a `run:` block with `bash -e {0}`, which has no pipefail. A step that pipes pytest into
    anything has to set it (`set -o pipefail`), or choose `shell: bash`, which GitHub starts with `-eo pipefail`.
    """

    WORKFLOWS = ROOT / ".github" / "workflows"

    @staticmethod
    def pipes_pytest(run: str) -> bool:
        """True if a command line runs pytest and pipes it (a `||` is not a pipe; a `\\` continuation is one line)."""
        joined = re.sub(r"\\\n\s*", " ", run)
        return any("pytest" in line and re.search(r"(?<!\|)\|(?!\|)", line) for line in joined.splitlines())

    @staticmethod
    def keeps_status(run: str, step: dict, job: dict) -> bool:
        shell = step.get("shell") or (job.get("defaults", {}).get("run", {}).get("shell")) or ""
        return "pipefail" in run or shell == "bash"

    def test_the_detector_reads_continuations_and_ignores_or(self):
        piped = 'python -m pytest tests/ \\\n  --cov=x \\\n  -q 2>&1 | tail -20\npython3 check.py'
        self.assertTrue(self.pipes_pytest(piped))
        self.assertFalse(self.pipes_pytest("python -m pytest tests/ -q || true"))
        self.assertFalse(self.pipes_pytest("python3 scripts/test_report.py --markers x --strict"))
        self.assertFalse(self.pipes_pytest("docker compose logs | tail -60"))

    def test_every_workflow_step_that_pipes_pytest_sets_pipefail(self):
        files = sorted(self.WORKFLOWS.glob("*.yml"))
        self.assertTrue(files, "no workflow files were found")
        offenders = []
        for path in files:
            for job_id, job in (yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs") or {}).items():
                for step in job.get("steps", []):
                    run = step.get("run", "")
                    if self.pipes_pytest(run) and not self.keeps_status(run, step, job):
                        offenders.append(f"{path.name} / {job_id} / {step.get('name', '(unnamed)')}")
        self.assertEqual(
            offenders,
            [],
            "these steps pipe pytest without pipefail, so a failing run exits with the pipe's status and the "
            f"step goes green (#275): {offenders}",
        )


class TestCoverageIsMeasuredOneWay(unittest.TestCase):
    """#274, #278: CI, the Makefile and the floors name the same scope, so they cannot drift apart again.

    CI measured `api/services`, the Makefile measured `build/csv` and `evals`, and nothing measured the rest of the
    API or the Streamlit app. Now all three say `api` and `streamlit_app`.
    """

    MAKEFILE = ROOT / "Makefile"

    @staticmethod
    def cov_scope(text: str) -> set[str]:
        return set(re.findall(r"--cov=([\w/.-]+)", text))

    def _ci_coverage_step(self) -> dict:
        steps = _load_workflow()["jobs"]["integration-postgres"]["steps"]
        found = [s for s in steps if "--cov" in s.get("run", "")]
        self.assertEqual(len(found), 1, "expected exactly one coverage step in the integration job")
        return found[0]

    def test_ci_measures_the_api_and_the_streamlit_app(self):
        self.assertEqual(self.cov_scope(self._ci_coverage_step()["run"]), {"api", "streamlit_app"})

    def test_the_makefile_measures_the_same_scope(self):
        text = self.MAKEFILE.read_text(encoding="utf-8")
        scope = re.search(r"^COVERAGE_SCOPE\s*:?=\s*(.*)$", text, re.M)
        self.assertIsNotNone(scope, "the Makefile has no COVERAGE_SCOPE")
        self.assertEqual(self.cov_scope(scope.group(1)), {"api", "streamlit_app"})
        for line in text.splitlines():
            self.assertNotIn("--cov=build/csv", line)
            self.assertNotIn("--cov=evals", line)

    def test_the_package_floors_are_for_exactly_that_scope(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import check_coverage_floors as gate
        finally:
            sys.path.pop(0)
        self.assertEqual({k.rstrip("/") for k in gate.PACKAGE_FLOORS}, {"api", "streamlit_app"})

    def test_ci_runs_the_floors_on_the_report_it_just_wrote(self):
        run = self._ci_coverage_step()["run"]
        report = re.search(r"--cov-report=json:(\S+)", run).group(1)
        self.assertIn(f"check_coverage_floors.py {report}", run)


if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()
