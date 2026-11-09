"""Checks for open issues that can be verified from the repository alone.

Each class says how far it goes. Nothing here closes an issue whose acceptance step is
manual or needs another system.

  #57  SECURITY.md is on main with a reporting channel
  #60  the air-gapped install procedure: scripts parse and the guide names them
       (the real offline dry run, due 15 Nov, is manual)
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
class SecurityPolicyIsPublished(unittest.TestCase):
    """#57: 'SECURITY.md is on main' is the issue's whole done-when."""

    TEXT = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

    def test_says_how_to_report_privately(self):
        self.assertIn("## Reporting a Vulnerability", self.TEXT)
        self.assertRegex(self.TEXT, r"(?i)do not open a public issue")

    def test_names_a_contact_address(self):
        self.assertRegex(self.TEXT, r"\*\*Email:\*\*\s*[\w.+-]+@[\w-]+\.[\w.]+")

    def test_says_which_versions_are_supported(self):
        self.assertIn("## Supported Versions", self.TEXT)


@pytest.mark.unit
class OfflineInstallProcedureIsConsistent(unittest.TestCase):
    """#60, as far as it can be checked without the offline VM."""

    SCRIPTS = sorted((ROOT / "scripts/offline").glob("*.sh"))
    GUIDE = (ROOT / "docs/offline-install.md").read_text(encoding="utf-8")

    def test_the_build_and_install_scripts_exist(self):
        self.assertTrue({"build_bundle.sh", "install.sh"} <= {p.name for p in self.SCRIPTS})

    def test_every_script_parses(self):
        for script in self.SCRIPTS:
            with self.subTest(script=script.name):
                res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stderr)

    def test_the_build_and_install_scripts_stop_on_the_first_error(self):
        # smoke_test.sh is excluded on purpose: it counts PASS/FAIL checks and exits non-zero at the end.
        for name in ("build_bundle.sh", "install.sh"):
            with self.subTest(script=name):
                self.assertRegex((ROOT / "scripts/offline" / name).read_text(encoding="utf-8"),
                                 r"(?m)^set -euo pipefail")

    def test_the_guide_names_the_scripts_it_relies_on(self):
        for name in ("build_bundle.sh", "install.sh"):
            with self.subTest(script=name):
                self.assertIn(name, self.GUIDE)

    def test_the_guide_gives_the_checksum_step(self):
        self.assertRegex(self.GUIDE, r"(?i)sha256")
