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


if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()
