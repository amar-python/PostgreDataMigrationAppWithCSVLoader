"""Checks for open issues that can be verified from the repository alone.

Each class says how far it goes. Nothing here closes an issue whose acceptance step is
manual or needs another system.

  #57  SECURITY.md is on main with a reporting channel
  #300 the channel is GitHub private vulnerability reporting, not a personal mailbox
  #60  the air-gapped install procedure: scripts parse and the guide names them
       (the real offline dry run, due 15 Nov, is manual)
"""

from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # tests/unit/ -> repo root


@pytest.mark.unit
class SecurityPolicyIsPublished(unittest.TestCase):
    """#57: 'SECURITY.md is on main' is the issue's whole done-when."""

    TEXT = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    def test_says_how_to_report_privately(self):
        self.assertIn("## Reporting a Vulnerability", self.TEXT)
        self.assertRegex(self.TEXT, r"(?i)do not open a public issue")

    PRIVATE_REPORT = r"https://github\.com/[\w.-]+/[\w.-]+/security/advisories/new"

    def test_names_a_private_reporting_channel(self):
        """An email address or GitHub's private reporting page; the policy chooses the latter (#300)."""
        email = re.search(r"\*\*Email:\*\*\s*[\w.+-]+@[\w-]+\.[\w.]+", self.TEXT)
        self.assertTrue(email or re.search(self.PRIVATE_REPORT, self.TEXT), "no way to report privately")

    def test_reports_go_through_githubs_private_vulnerability_reporting(self):
        self.assertRegex(self.TEXT, self.PRIVATE_REPORT)
        self.assertIn("Report a vulnerability", self.TEXT)

    def test_has_no_personal_placeholder_address_or_open_todo(self):
        self.assertNotRegex(self.TEXT, r"(?i)@(gmail|outlook|hotmail|yahoo)\.")
        self.assertNotIn("TODO", self.TEXT)
        self.assertNotIn("Tracked in #57", self.TEXT)

    def test_does_not_tell_reporters_to_email_first(self):
        self.assertNotRegex(self.TEXT, r"(?i)first email")

    def test_says_which_versions_are_supported(self):
        self.assertIn("## Supported Versions", self.TEXT)


@pytest.mark.unit
class OfflineInstallProcedureIsConsistent(unittest.TestCase):
    """#60, as far as it can be checked without the offline VM."""

    SCRIPTS = sorted((ROOT / "scripts/offline").glob("*.sh"))
    GUIDE = (ROOT / "docs/offline-install.md").read_text(encoding="utf-8")

    def test_the_build_and_install_scripts_exist(self):
        self.assertTrue({"build_bundle.sh", "install.sh"} <= {p.name for p in self.SCRIPTS})

    def test_the_build_and_install_scripts_stop_on_the_first_error(self):
        # smoke_test.sh is excluded on purpose: it counts PASS/FAIL checks and exits non-zero at the end.
        for name in ("build_bundle.sh", "install.sh"):
            with self.subTest(script=name):
                self.assertRegex(
                    (ROOT / "scripts/offline" / name).read_text(encoding="utf-8"), r"(?m)^set -euo pipefail"
                )

    def test_the_guide_names_the_scripts_it_relies_on(self):
        for name in ("build_bundle.sh", "install.sh"):
            with self.subTest(script=name):
                self.assertIn(name, self.GUIDE)

    def test_the_guide_gives_the_checksum_step(self):
        self.assertRegex(self.GUIDE, r"(?i)sha256")


@pytest.mark.tooling
class OfflineScriptsParse(unittest.TestCase):
    """#60: `bash -n` on each offline script. Needs bash, so it is marked tooling (not run on Windows)."""

    def test_every_script_parses(self):
        for script in sorted((ROOT / "scripts/offline").glob("*.sh")):
            with self.subTest(script=script.name):
                res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stderr)
