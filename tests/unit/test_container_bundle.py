"""#128 (BR-38): static guards on the container bundle. No Docker needed.

The bundle installs the platform from images that were saved on a build machine, with no
internet access. What these tests pin is what could silently break that, and what no
other test would notice:

  * the compose file only ever uses images from the bundle (no `build:`, never a pull),
    and takes its secrets from variables, not literals;
  * every file a Dockerfile copies exists, and none is a file that holds credentials
    (the same rule as tests/unit/test_docker_image_secrets.py, #174, for the Azure image);
  * the scripts parse, and the PowerShell installer avoids the two things that break it
    on Windows;
  * the smoke test's pass/fail logic, run against a fake server.

Building and running the images is exercised by .github/workflows/container-bundle.yml.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = ROOT / "container"
IMAGES = ("api", "frontend", "db")

# Files that hold credentials and must never be copied into an image (RV-S4, #174).
SENSITIVE = (
    "build/config.local.env",
    "build/environments/env_dev.sql",
    "build/environments/env_test.sql",
    "build/environments/env_staging.sql",
    "build/environments/env_prod.sql",
)


def compose() -> dict:
    return yaml.safe_load((CONTAINER / "docker-compose.yml").read_text(encoding="utf-8"))


def copy_sources(dockerfile: Path) -> list[str]:
    """Source paths of every COPY in a Dockerfile (skipping --from=stage copies)."""
    sources: list[str] = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*COPY\s+(.+?)\s*$", line, re.IGNORECASE)
        if not m:
            continue
        tokens = m.group(1).split()
        if any(t.startswith("--from=") for t in tokens):
            continue
        sources.extend(t for t in tokens[:-1] if not t.startswith("--"))
    return sources


@pytest.mark.unit
class ComposeUsesOnlyBundledImages(unittest.TestCase):
    def test_every_service_is_a_te_image_that_is_never_pulled_or_built(self):
        services = compose()["services"]
        self.assertEqual(sorted(services), sorted(IMAGES))
        for name, svc in services.items():
            with self.subTest(service=name):
                self.assertNotIn("build", svc, "the installer has no build tools or internet; images come from the bundle")
                self.assertRegex(svc["image"], rf"^te-{name}:\$\{{TE_VERSION")
                self.assertEqual(svc.get("pull_policy"), "never", "a missing image must be an error, not a download")

    def test_the_web_app_and_api_ports_are_published(self):
        services = compose()["services"]
        self.assertIn("8000:8000", services["api"]["ports"])
        self.assertIn("8080:8080", services["frontend"]["ports"])
        self.assertNotIn("ports", services["db"], "the database is reached over the compose network only")

    def test_secrets_come_from_variables_not_literals(self):
        services = compose()["services"]
        for svc, var in (("db", "POSTGRES_PASSWORD"), ("db", "TE_DB_PASSWORD"), ("db", "TE_RUNTIME_PASSWORD"),
                         ("api", "API_KEY"), ("api", "PGPASSWORD"), ("api", "APP_DB_PASSWORD")):
            with self.subTest(service=svc, variable=var):
                self.assertRegex(str(services[svc]["environment"][var]), r"^\$\{[A-Z_]+:\?",
                                 "a secret must be required from .env, never written in the file")

    def test_database_data_is_on_a_named_volume(self):
        self.assertIn("te-db", compose()["volumes"])
        self.assertTrue(any(v.startswith("te-db:") for v in compose()["services"]["db"]["volumes"]))

    def test_no_healthcheck_passes_arguments_with_spaces_in_the_exec_form(self):
        """Podman splits the arguments of the `CMD` array form on spaces when they arrive through a compose
        provider, so `python -c "<code>"` ran as `python -c import` and the API was never healthy. A
        single string (`CMD-SHELL`) survives. Found by running the install under Podman."""
        for name, svc in compose()["services"].items():
            test = svc.get("healthcheck", {}).get("test", [])
            if test and test[0] == "CMD":
                with self.subTest(service=name):
                    self.assertFalse([a for a in test[1:] if re.search(r"\s", a)],
                                     "use CMD-SHELL with one string, or put the command in a script")

    def test_the_api_waits_for_a_healthy_database_and_the_web_app_for_the_api(self):
        services = compose()["services"]
        self.assertEqual(services["api"]["depends_on"]["db"]["condition"], "service_healthy")
        self.assertEqual(services["frontend"]["depends_on"]["api"]["condition"], "service_healthy")


@pytest.mark.unit
class DockerfilesCopyOnlyWhatExists(unittest.TestCase):
    def test_each_image_has_a_dockerfile_that_build_bundle_builds(self):
        script = (CONTAINER / "build_bundle.sh").read_text(encoding="utf-8")
        self.assertIn("for img in " + " ".join(IMAGES), script)
        for img in IMAGES:
            with self.subTest(image=img):
                self.assertTrue((CONTAINER / f"{img}.Dockerfile").is_file())

    def test_every_copied_file_exists_and_none_holds_credentials(self):
        for img in IMAGES:
            for src in copy_sources(CONTAINER / f"{img}.Dockerfile"):
                with self.subTest(image=img, source=src):
                    self.assertTrue((ROOT / src).exists(), f"{src} does not exist; a rename would break the image build")
                    self.assertNotIn(src.rstrip("/"), SENSITIVE)
                    self.assertNotEqual(src.rstrip("/"), "build", "copy named files, not the whole build/ tree: it can hold config.local.env")

    def test_no_secret_is_baked_into_an_image(self):
        for img in IMAGES:
            text = (CONTAINER / f"{img}.Dockerfile").read_text(encoding="utf-8")
            with self.subTest(image=img):
                self.assertNotRegex(text, r"(?im)^\s*(ENV|ARG)\s+\w*(PASSWORD|API_KEY|SECRET)\w*[= ]",
                                    "credentials arrive as run-time environment variables, never in a layer")


@pytest.mark.unit
class PowerShellInstallerAvoidsWindowsTraps(unittest.TestCase):
    code = "\n".join(l for l in (CONTAINER / "install.ps1").read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))

    def test_the_env_file_is_written_without_a_byte_order_mark(self):
        """-Encoding UTF8 adds a BOM in Windows PowerShell 5.1; a .env parser then reads it as part of the first key."""
        self.assertNotRegex(self.code, r"(?i)-Encoding\s+UTF8")
        self.assertIn("UTF8Encoding($false)", self.code)

    def test_native_stderr_does_not_become_a_terminating_error(self):
        """Docker writes progress to stderr; under 'Stop', PowerShell 5.1 would abort the install on it."""
        self.assertNotRegex(self.code, r"\$ErrorActionPreference\s*=\s*'Stop'")

    def test_the_file_is_checked_out_with_windows_line_endings(self):
        self.assertRegex((ROOT / ".gitattributes").read_text(encoding="utf-8"), r"(?m)^\*\.ps1\s+text\s+eol=crlf")


@pytest.mark.tooling
class ScriptsParse(unittest.TestCase):
    def test_shell_scripts_have_no_syntax_errors(self):
        for name in ("install.sh", "build_bundle.sh", "db-init.sh", "frontend-entrypoint.sh"):
            with self.subTest(script=name):
                res = subprocess.run(["bash", "-n", str(CONTAINER / name)], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0, res.stderr)

    def test_the_installer_uses_nothing_newer_than_bash_3_2(self):
        """macOS ships bash 3.2: no associative arrays, mapfile, or ${var,,} / ${var^^}."""
        code = "\n".join(l for l in (CONTAINER / "install.sh").read_text(encoding="utf-8").splitlines()
                         if not l.lstrip().startswith("#"))
        for pattern in (r"declare\s+-A", r"\bmapfile\b", r"\breadarray\b", r"\$\{[A-Za-z_]+(,,|\^\^)\}", r"&>>"):
            with self.subTest(pattern=pattern):
                self.assertNotRegex(code, pattern)


class _FakeStack(BaseHTTPRequestHandler):
    """Answers like the API and the web app, to drive container/smoke_test.py."""

    broken: set[str] = set()

    def log_message(self, *args):  # keep test output quiet
        pass

    def _send(self, status: int, body: str, ctype: str = "application/json") -> None:
        data = body.encode()
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        authed = self.headers.get("X-API-Key") == "k" or self.headers.get("Authorization") == "Bearer tok"
        if self.path == "/api/health":
            self._send(200, '{"status":"ok"}')
        elif self.path == "/api/csv/files":
            if "no401" in self.broken:
                self._send(200, "[]")
            else:
                self._send(200, '[{"file_name":"x","total_rows":2}]') if authed else self._send(401, "{}")
        elif self.path == "/api/auth/me":
            self._send(200, '{"role":"%s"}' % ("viewer" if "role" in self.broken else "tenant_admin"))
        elif self.path == "/":
            self._send(200, "<html><body>app</body></html>", "text/html")
        else:
            self._send(404, "{}")

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path == "/api/csv/upload":
            self._send(200, '{"insertedRows": %d}' % (0 if "upload" in self.broken else 2))
        elif self.path == "/api/auth/login":
            self._send(200, '{"token":"tok"}')
        else:
            self._send(404, "{}")


@pytest.mark.unit
class SmokeTestLogic(unittest.TestCase):
    """The smoke test is the install's proof; it must pass when the stack is right and fail when it is not."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeStack)
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def run_smoke(self, *, broken: set[str] = frozenset(), with_login: bool = True):
        _FakeStack.broken = set(broken)
        env = {k: v for k, v in os.environ.items() if not k.startswith("SMOKE_") and k != "API_KEY"}
        env.update(API_URL=self.url, FRONTEND_URL=self.url, API_KEY="k")
        if with_login:
            env.update(SMOKE_TENANT="main", SMOKE_USER="admin", SMOKE_PASSWORD="long-enough-password")
        return subprocess.run([sys.executable, str(CONTAINER / "smoke_test.py")], env=env,
                              capture_output=True, text=True, timeout=60)

    def test_a_healthy_stack_passes_all_seven(self):
        res = self.run_smoke()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("7 of 7 passed", res.stdout)
        self.assertEqual(res.stdout.count("PASS  "), 7)

    def test_without_admin_credentials_it_runs_five_and_says_so(self):
        res = self.run_smoke(with_login=False)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("5 of 5 passed", res.stdout)
        self.assertIn("SKIP", res.stdout)

    def test_each_failure_is_reported_and_fails_the_run(self):
        for breakage, label in (("no401", "API rejects a missing key"), ("upload", "upload a CSV"),
                                ("role", "session is tenant_admin")):
            with self.subTest(breakage=breakage):
                res = self.run_smoke(broken={breakage})
                self.assertNotEqual(res.returncode, 0, res.stdout)
                self.assertIn(f"FAIL  {label}", res.stdout)
                self.assertNotIn("7 of 7", res.stdout)

    def test_it_refuses_to_run_without_the_api_key(self):
        env = {k: v for k, v in os.environ.items() if k != "API_KEY"}
        res = subprocess.run([sys.executable, str(CONTAINER / "smoke_test.py")], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 2)

    def test_the_script_parses_and_defines_seven_checks(self):
        tree = ast.parse((CONTAINER / "smoke_test.py").read_text(encoding="utf-8"))
        consts = {n.targets[0].id: n.value.value for n in tree.body
                  if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and isinstance(n.value, ast.Constant)}
        self.assertEqual(consts.get("TOTAL"), 7)


if __name__ == "__main__":
    unittest.main()
