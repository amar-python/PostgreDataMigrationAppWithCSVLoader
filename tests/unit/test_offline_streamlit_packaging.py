"""#256 (migration step 5): the Streamlit app in the offline Ubuntu bundle, beside the React app.

What the scripts must do, checked from the repository (the clean-VM dry run, #60, is the owner's):

* build_bundle.sh downloads the Streamlit wheels with exactly the flags it uses for the API's
  (CPython 3.12, manylinux x86_64, binary wheels only), and still builds the React frontend (#257 removes it);
* install.sh installs them offline into their own venv and adds a te-streamlit systemd unit that runs
  `python -m streamlit run app.py` from streamlit_app/ (so the shipped config.toml turns telemetry off), with
  API_URL and MAX_UPLOAD_BYTES in an env file that holds no database password;
* smoke_test.sh checks /_stcore/health, and a Streamlit that does not answer "ok" is a FAIL;
* docs/offline-install.md lists exactly the PASS lines the smoke test prints.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OFFLINE = ROOT / "scripts/offline"
BUILD = (OFFLINE / "build_bundle.sh").read_text(encoding="utf-8")
INSTALL = (OFFLINE / "install.sh").read_text(encoding="utf-8")
SMOKE = (OFFLINE / "smoke_test.sh").read_text(encoding="utf-8")
GUIDE = (ROOT / "docs/offline-install.md").read_text(encoding="utf-8")
CONFIG = tomllib.loads((ROOT / "streamlit_app/.streamlit/config.toml").read_text(encoding="utf-8"))


def heredoc(text: str, opener: str) -> str:
    """The body of the heredoc whose first line contains `opener`, up to its terminator."""
    m = re.search(re.escape(opener) + r"[^\n]*<<(\w+)\n(.*?)\n\1\n", text, re.S)
    assert m, f"no heredoc for {opener!r}"
    return m.group(2)


@pytest.mark.unit
class BundleCarriesTheStreamlitWheels(unittest.TestCase):
    def test_streamlit_requirements_are_downloaded(self):
        # From the hashed lock (#327), compiled from streamlit_app/requirements.txt.
        self.assertRegex(BUILD, r"pip download[^\n]*-r streamlit_app/requirements\.lock")

    def test_both_wheel_sets_use_one_set_of_flags(self):
        lines = [ln for ln in BUILD.splitlines() if "pip download" in ln and "-r " in ln]
        self.assertEqual(len(lines), 2, lines)
        for ln in lines:
            with self.subTest(line=ln):
                self.assertIn('"${WHEEL_FLAGS[@]}"', ln)

    def test_the_flags_pin_cpython_312_manylinux_x86_64_binary_only(self):
        flags = re.search(r"WHEEL_FLAGS=\((.*?)\)", BUILD, re.S).group(1)
        for flag in (
            "--only-binary=:all:",
            "--python-version 3.12",
            "--implementation cp",
            "--platform manylinux2014_x86_64",
            "--platform manylinux_2_17_x86_64",
            "--platform manylinux_2_28_x86_64",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, flags)

    def test_the_react_frontend_is_still_built(self):
        """Ship alongside, not instead: React stays the default until #257."""
        self.assertIn("npm ci", BUILD)
        self.assertIn('"$OUT/frontend"', BUILD)


@pytest.mark.unit
class InstallAddsTheStreamlitService(unittest.TestCase):
    UNIT = heredoc(INSTALL, "/etc/systemd/system/te-streamlit.service")
    ST_ENV = heredoc(INSTALL, '"$DEST/streamlit.env"')
    API_ENV = heredoc(INSTALL, '"$DEST/env"')

    def test_the_venv_is_built_offline_from_the_bundle(self):
        self.assertRegex(
            INSTALL,
            r'streamlit-venv/bin/pip" install -q --no-index --find-links "\$BUNDLE/wheels" '
            r"--require-hashes --no-deps \\\n"
            r'\s+-r "\$DEST/app/streamlit_app/requirements\.lock"',
        )

    def test_the_unit_runs_streamlit_from_streamlit_app(self):
        self.assertRegex(self.UNIT, r"(?m)^ExecStart=\$DEST/streamlit-venv/bin/python -m streamlit run app\.py ")
        self.assertRegex(self.UNIT, r"(?m)^WorkingDirectory=\$DEST/app/streamlit_app$")
        self.assertRegex(self.UNIT, r"(?m)^User=te-app$")

    def test_the_unit_runs_headless_on_port_8501(self):
        exec_start = re.search(r"(?m)^ExecStart=.*$", self.UNIT).group(0)
        self.assertIn("--server.headless true", exec_start)
        self.assertIn("--server.port 8501", exec_start)

    def test_the_unit_reads_its_own_env_file(self):
        self.assertRegex(self.UNIT, r"(?m)^EnvironmentFile=\$DEST/streamlit\.env$")

    def test_its_env_file_has_the_api_address_and_the_upload_limit_and_no_password(self):
        self.assertRegex(self.ST_ENV, r"(?m)^API_URL=http://localhost:8000$")
        self.assertRegex(self.ST_ENV, r"(?m)^MAX_UPLOAD_BYTES=\$MAX_UPLOAD_BYTES$")
        self.assertNotRegex(self.ST_ENV, r"PASSWORD|PGUSER")
        self.assertIn('chmod 600 "$DEST/streamlit.env"', INSTALL)

    def test_the_api_gets_the_same_upload_limit(self):
        self.assertRegex(self.API_ENV, r"(?m)^MAX_UPLOAD_BYTES=\$MAX_UPLOAD_BYTES$")

    def test_streamlits_own_limit_stays_above_the_default(self):
        """Streamlit counts 1,000,000-byte megabytes; it must never refuse a file the API would take."""
        default = int(re.search(r'MAX_UPLOAD_BYTES="\$\{MAX_UPLOAD_BYTES:-(\d+)\}"', INSTALL).group(1))
        self.assertEqual(default, 50 * 1024 * 1024)
        self.assertGreater(CONFIG["server"]["maxUploadSize"] * 1_000_000, default)

    def test_the_shipped_config_turns_telemetry_off(self):
        self.assertIs(CONFIG["browser"]["gatherUsageStats"], False)

    def test_all_three_services_are_started_and_react_is_kept(self):
        self.assertRegex(INSTALL, r"(?m)^systemctl enable --now te-api te-frontend te-streamlit")
        self.assertIn("/etc/systemd/system/te-frontend.service", INSTALL)


def _fake_bin(d: Path, st_health: str) -> Path:
    """A curl that answers like a healthy install, except Streamlit's health says `st_health`; a no-op sleep."""
    bin_dir = d / "bin"
    bin_dir.mkdir()
    (bin_dir / "curl").write_text(f"""#!/bin/bash
url="${{@: -1}}"
case "$*" in *'%{{http_code}}'*) echo -n 401; exit 0;; esac
case "$url" in
  */_stcore/health) [ -n "{st_health}" ] || exit 7; echo -n "{st_health}";;
  */api/health) echo '{{"status":"ok"}}';;
  */api/auth/login) echo '{{"token":"t0k"}}';;
  */api/auth/me) echo '{{"role":"tenant_admin"}}';;
  */api/csv/upload) echo '{{"insertedRows":2}}';;
  */api/csv/files) echo '[{{"total_rows":2}}]';;
  *) echo '<html><body>app</body></html>';;
esac
""")
    (bin_dir / "sleep").write_text("#!/bin/bash\nexit 0\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    return bin_dir


@pytest.mark.tooling
class SmokeTestChecksStreamlit(unittest.TestCase):
    def _run(self, st_health: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as d:
            env = {
                **os.environ,
                "PATH": f"{_fake_bin(Path(d), st_health)}:{os.environ['PATH']}",
                "SMOKE_TENANT": "main",
                "SMOKE_USER": "admin",
                "SMOKE_PASSWORD": "pw",
            }
            return subprocess.run(
                ["bash", str(OFFLINE / "smoke_test.sh")], capture_output=True, text=True, env=env, timeout=60
            )

    def test_a_healthy_streamlit_passes(self):
        res = self._run("ok")
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("PASS  Streamlit app health", res.stdout)
        self.assertNotIn("FAIL", res.stdout)

    def test_a_streamlit_that_is_down_fails(self):
        res = self._run("")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("FAIL  Streamlit app health", res.stdout)

    def test_an_answer_other_than_ok_fails(self):
        res = self._run("starting")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("FAIL  Streamlit app health", res.stdout)


@pytest.mark.unit
class GuideMatchesTheSmokeTest(unittest.TestCase):
    def test_the_guide_lists_exactly_the_pass_lines_the_smoke_test_prints(self):
        printed = re.findall(r'pass "([^"]+)"', SMOKE)
        block = re.search(r"```\n(PASS  .*?)\n```", GUIDE, re.S).group(1)
        self.assertEqual([ln[len("PASS  ") :] for ln in block.splitlines()], printed)

    def test_the_guide_gives_the_number_of_pass_lines(self):
        n = len(re.findall(r'pass "([^"]+)"', SMOKE))
        self.assertEqual(n, 8)
        self.assertIn("these eight lines", GUIDE)
        self.assertIn("all eight PASS lines", GUIDE)

    def test_the_guide_names_the_streamlit_service_port_and_health_endpoint(self):
        for text in ("te-streamlit", "8501", "/_stcore/health", "gatherUsageStats = false", "MAX_UPLOAD_BYTES"):
            with self.subTest(text=text):
                self.assertIn(text, GUIDE)

    def test_the_guide_keeps_the_untested_telemetry_claim_open(self):
        self.assertIn("has not been tested", GUIDE)
