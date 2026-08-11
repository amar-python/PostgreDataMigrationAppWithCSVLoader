"""CI quality gate structure tests — verify workflow correctness offline.

Validates that quality-gate.yml has the expected jobs, steps, and
configuration. Catches accidental removals or misconfigurations before
they reach CI. No database or network required.
"""
import unittest
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "quality-gate.yml"
GAP_ANALYSIS = ROOT / "GAP_ANALYSIS.md"


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

        self.assertIn("windows-postgres", self.jobs)

    def test_triggers_on_pull_request(self):
        # PyYAML parses the YAML key `on` as boolean True
        triggers = self.wf.get(True, self.wf.get("on", {}))
        self.assertIn("pull_request", triggers)

    def test_triggers_on_push_to_main(self):
        triggers = self.wf.get(True, self.wf.get("on", {}))
        push_branches = triggers.get("push", {}).get("branches", [])
        self.assertIn("main", push_branches)



class TestAllJobsHaveConsistentStructure(unittest.TestCase):
    """Every job must have checkout + install-deps. Python jobs additionally
    need Python setup and an artifact upload; Node jobs need Node setup.

    BUG-023 added the Node-backed ``frontend-build`` job, so the old
    "every job needs Python" contract needed to split by job kind. Any new
    job MUST be classified in PYTHON_JOBS or NODE_JOBS below — an
    unclassified job fails setUpClass, so a contributor can't quietly bypass
    the structural rules.
    """

    PYTHON_JOBS = {"free-tier", "integration-postgres", "windows-postgres"}
    NODE_JOBS = {"frontend-build"}

    @classmethod
    def setUpClass(cls):
        if not WORKFLOW.exists():
            raise AssertionError(f"Workflow file not found: {WORKFLOW}")
        cls.jobs = _load_workflow().get("jobs", {})
        unclassified = set(cls.jobs) - cls.PYTHON_JOBS - cls.NODE_JOBS
        if unclassified:
            raise AssertionError(
                f"quality-gate.yml has unclassified jobs: {sorted(unclassified)}. "
                f"Add each to PYTHON_JOBS or NODE_JOBS in {__file__}."
            )

    def _step_names(self, job_id: str) -> list[str]:
        return [s.get("name", "") for s in self.jobs[job_id].get("steps", [])]

    def test_all_jobs_have_checkout(self):
        for job_id in self.jobs:
            names = self._step_names(job_id)
            self.assertTrue(
                any("Checkout" in n for n in names),
                f"Job {job_id!r} missing Checkout step",
            )

    def test_all_jobs_install_deps(self):
        # "Install dependencies" (Node) and "Install dev dependencies" (Python)
        # both match: literal "Install" plus lowercase "dep".
        for job_id in self.jobs:
            names = self._step_names(job_id)
            self.assertTrue(
                any("Install" in n and "dep" in n.lower() for n in names),
                f"Job {job_id!r} missing install dependencies step",
            )

    def test_python_jobs_have_python_setup(self):
        for job_id in self.PYTHON_JOBS:
            if job_id not in self.jobs:
                continue
            names = self._step_names(job_id)
            self.assertTrue(
                any("Setup Python" in n or "Python" in n for n in names),
                f"Python job {job_id!r} missing Python setup step",
            )

    def test_python_jobs_have_artifact_upload(self):
        for job_id in self.PYTHON_JOBS:
            if job_id not in self.jobs:
                continue
            names = self._step_names(job_id)
            self.assertTrue(
                any("Upload" in n for n in names),
                f"Python job {job_id!r} missing artifact upload step",
            )

    def test_node_jobs_have_node_setup(self):
        for job_id in self.NODE_JOBS:
            if job_id not in self.jobs:
                continue
            names = self._step_names(job_id)
            self.assertTrue(
                any("Setup Node" in n or "Node" in n for n in names),
                f"Node job {job_id!r} missing Node setup step",
            )


class TestGapAnalysisG2Closed(unittest.TestCase):
    """GAP_ANALYSIS.md must show G2 as Closed."""

    @classmethod
    def setUpClass(cls):
        if not GAP_ANALYSIS.exists():
            raise AssertionError(f"GAP_ANALYSIS.md not found: {GAP_ANALYSIS}")
        cls.content = GAP_ANALYSIS.read_text(encoding="utf-8")

    def test_g2_row_shows_closed(self):
        for line in self.content.splitlines():
            if "| G2 |" in line:
                self.assertIn("**Closed**", line,
                              "G2 row must show **Closed**")
                return
        self.fail("G2 row not found in GAP_ANALYSIS.md")

    def test_g2_row_has_strikethrough(self):
        for line in self.content.splitlines():
            if "| G2 |" in line:
                self.assertIn("~~", line,
                              "G2 row must have strikethrough on the gap description")
                return
        self.fail("G2 row not found in GAP_ANALYSIS.md")

    def test_g2_section_says_closed(self):
        self.assertIn("### G2", self.content)
        self.assertIn("G2 — Windows CI cannot host PostgreSQL (Closed)",
                       self.content)

    def test_g2_section_mentions_quality_gate(self):
        g2_start = self.content.index("### G2")
        g3_start = self.content.index("### G3")
        g2_section = self.content[g2_start:g3_start]
        self.assertIn("quality-gate.yml", g2_section)
        self.assertIn("windows-postgres", g2_section)


if __name__ == "__main__":
    unittest.main()
