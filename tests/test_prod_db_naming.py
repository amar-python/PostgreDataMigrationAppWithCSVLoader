"""Terraform, the deployer and the container entrypoint agree on the production database (#172).

Before: Terraform created `te_prod` owned by `pgadmin`, the deployer created `te_mgmt_prod` owned
by `postgres`, and the entrypoint expected an `env_prod.sql` that nothing in the image produced.

No database needed: the deployer runs with --dry-run, the entrypoint with its `render` action, and
the Terraform file is read as text. The fresh-server run is recorded on the PR.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
ENTRYPOINT = ROOT / "infra" / "entrypoint.sh"
TERRAFORM = (ROOT / "infra" / "terraform-prod" / "main.tf").read_text(encoding="utf-8")
SCHEMA_SQL = BUILD / "te_core_schema.sql"
SECRET = "S3cr3t'\"$(touch /tmp/should-not-exist)"


def _find_bash():
    """A real bash. On Windows the PATH `bash` is the WSL launcher, which fails when no distribution is
    installed, so use Git Bash explicitly (as test_csv_utilise.py does). None if there isn't one."""
    if sys.platform == "win32":
        for candidate in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
            if Path(candidate).exists():
                return candidate
        found = shutil.which("bash")
        return found if found and "system32" not in found.lower() else None
    return shutil.which("bash") or "bash"


_BASH = _find_bash()


def _posix(path: Path) -> str:
    """Forward slashes, which Git Bash and Linux bash both read; Windows backslashes are escapes to bash."""
    return path.as_posix()


def _bash(args: list[str], env: dict[str, str | None]) -> subprocess.CompletedProcess:
    """Run bash with the caller's environment plus ``env``; a None value removes that variable."""
    full_env = dict(os.environ)  # Git Bash on Windows needs SYSTEMROOT, TEMP and the like
    for key, value in env.items():
        if value is None:
            full_env.pop(key, None)
        else:
            full_env[key] = value
    # The scripts print UTF-8 symbols; the Windows locale codec cannot decode them.
    return subprocess.run([_BASH, *args], env=full_env, capture_output=True, encoding="utf-8",
                          errors="replace", timeout=60)


def _require_bash() -> None:
    if _BASH is None:
        raise AssertionError("No working bash found: install Git Bash and ensure it is on PATH.")


def _tf_env(name: str) -> str | None:
    m = re.search(r'env\s*\{\s*name\s*=\s*"%s"\s*(?:value|secret_name)\s*=\s*([^\n]+)' % name, TERRAFORM)
    return m.group(1).strip().strip('"') if m else None


@pytest.mark.unit
class DeployerReadsNamesFromTheLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _require_bash()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deploy_names_"))
        (self.tmp / "build").mkdir()
        shutil.copy(BUILD / "deploy_all.sh", self.tmp / "build" / "deploy_all.sh")
        shutil.copytree(BUILD / "environments", self.tmp / "build" / "environments")
        for env in ("dev", "test", "staging", "prod"):
            shutil.copy(self.tmp / "build" / "environments" / f"env_{env}.example.sql",
                        self.tmp / "build" / "environments" / f"env_{env}.sql")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _launcher(self, env: str) -> Path:
        return self.tmp / "build" / "environments" / f"env_{env}.sql"

    def _dry_run(self, *envs: str) -> subprocess.CompletedProcess:
        # PGHOST is unreachable on purpose: a dry run must not touch PostgreSQL.
        return _bash([_posix(self.tmp / "build" / "deploy_all.sh"), "--dry-run", *envs],
                     {"PGHOST": "/nonexistent-socket-dir"})

    def _write_launcher(self, env: str, text: str) -> None:
        self._launcher(env).write_text(text, encoding="utf-8", newline="\n")

    def test_committed_templates_keep_the_on_prem_names(self):
        out = self._dry_run().stdout
        for env, db in (("DEV", "te_mgmt_dev"), ("TEST", "te_mgmt_test"),
                        ("STAGING", "te_mgmt_staging"), ("PROD", "te_mgmt_prod")):
            self.assertRegex(out, rf"{env}\s+\(database: {db}, owner: postgres\)")

    def test_the_launcher_decides_the_database_and_owner(self):
        text = self._launcher("prod").read_text(encoding="utf-8")
        text = re.sub(r"(\\set db_name\s+).*", r"\1te_prod", text)
        text = re.sub(r"(\\set db_owner\s+).*", r"\1pgadmin", text)
        self._write_launcher("prod", text)
        res = self._dry_run("prod")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertRegex(res.stdout, r"PROD\s+\(database: te_prod, owner: pgadmin\)")

    def test_a_launcher_that_sets_neither_falls_back_to_the_on_prem_names(self):
        lines = [ln for ln in self._launcher("prod").read_text(encoding="utf-8").splitlines()
                 if not re.match(r"\\set (db_name|db_owner)\b", ln)]
        self._write_launcher("prod", "\n".join(lines))
        self.assertRegex(self._dry_run("prod").stdout, r"database: te_mgmt_prod, owner: postgres")

    def test_an_unsafe_identifier_is_refused(self):
        text = re.sub(r"(\\set db_name\s+).*", r'\1"x; DROP DATABASE y"',
                      self._launcher("prod").read_text(encoding="utf-8"))
        self._write_launcher("prod", text)
        res = self._dry_run("prod")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Unsafe identifier", res.stderr)


@pytest.mark.unit
class EntrypointWritesTheLauncher(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _require_bash()

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="entrypoint_home_"))
        # The image carries the templates only; the concrete launchers are gitignored and absent.
        (self.home / "build" / "environments").mkdir(parents=True)
        for template in (BUILD / "environments").glob("env_*.example.sql"):
            shutil.copy(template, self.home / "build" / "environments" / template.name)
        self.env = {"MIGRATION_HOME": _posix(self.home), "TARGET_ENV": "prod", "PGHOST": "unused",
                    "PGPORT": "5432", "PGUSER": "pgadmin", "PGDATABASE": "te_prod",
                    "WAIT_FOR_DB_SECONDS": "1", "APP_DB_PASSWORD": SECRET}

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)
        self.assertFalse(Path("/tmp/should-not-exist").exists(), "the password was executed as shell")

    def _render(self, **override) -> subprocess.CompletedProcess:
        return _bash([_posix(ENTRYPOINT), "render"], {**self.env, **override})

    def test_the_image_has_no_concrete_launcher(self):
        self.assertEqual([p.name for p in (self.home / "build" / "environments").glob("env_*.sql")
                          if not p.name.endswith(".example.sql")], [])

    def test_the_launcher_is_made_from_the_containers_database_and_user(self):
        res = self._render()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertRegex(res.stdout, r"\\set db_name\s+te_prod\b")
        self.assertRegex(res.stdout, r"\\set db_owner\s+pgadmin\b")
        self.assertIn(r"\ir ../te_core_schema.sql", res.stdout)

    def test_the_password_is_read_by_psql_and_never_written(self):
        res = self._render()
        self.assertIn(r"\getenv app_password APP_DB_PASSWORD", res.stdout)
        written = (self.home / "build" / "environments" / "env_prod.sql").read_text(encoding="utf-8")
        self.assertNotIn("S3cr3t", written)
        self.assertNotIn("S3cr3t", res.stdout + res.stderr)
        self.assertNotIn("__INJECT_AT_DEPLOY__", written)

    def test_a_missing_password_is_an_error(self):
        res = self._render(APP_DB_PASSWORD=None)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("APP_DB_PASSWORD is not set", res.stderr)

    def test_an_unsafe_database_name_is_an_error(self):
        res = self._render(PGDATABASE="te_prod; DROP DATABASE x")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("lower-case letters", res.stderr)

    def test_an_existing_launcher_is_left_alone(self):
        mine = self.home / "build" / "environments" / "env_prod.sql"
        mine.write_text("\\set db_name mounted_db\n", encoding="utf-8")
        res = self._render()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(mine.read_text(encoding="utf-8"), "\\set db_name mounted_db\n")

    def test_an_environment_with_no_template_is_an_error(self):
        res = self._render(TARGET_ENV="qa")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("no launcher for TARGET_ENV='qa'", res.stderr)


@pytest.mark.unit
class TerraformAgreesWithTheDeployment(unittest.TestCase):
    def test_the_database_terraform_creates_is_te_prod(self):
        m = re.search(r'resource "azurerm_postgresql_flexible_server_database" "te_prod"\s*\{[^}]*?name\s*=\s*"([^"]+)"',
                      TERRAFORM)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "te_prod")

    def test_the_job_deploys_into_that_database_as_the_servers_admin(self):
        admin = re.search(r'administrator_login\s*=\s*"([^"]+)"', TERRAFORM).group(1)
        self.assertEqual(_tf_env("PGUSER"), admin)
        self.assertEqual(_tf_env("PGDATABASE"), "azurerm_postgresql_flexible_server_database.te_prod.name")

    def test_the_job_receives_the_application_password_as_a_secret(self):
        self.assertEqual(_tf_env("APP_DB_PASSWORD"), "app-password")
        self.assertRegex(TERRAFORM, r'secret\s*\{\s*name\s*=\s*"app-password"[^}]*azurerm_key_vault_secret\.app_password\.id')

    def test_every_extension_the_schema_creates_is_allow_listed_on_azure(self):
        needed = set(re.findall(r'CREATE EXTENSION IF NOT EXISTS "([^"]+)"', SCHEMA_SQL.read_text(encoding="utf-8")))
        self.assertTrue(needed, "expected the schema to create extensions")
        m = re.search(r'name\s*=\s*"azure\.extensions"[^}]*?value\s*=\s*"([^"]+)"', TERRAFORM)
        self.assertIsNotNone(m, "azure.extensions is not set")
        self.assertLessEqual(needed, set(m.group(1).split(",")))


@pytest.mark.unit
class DeploymentOutputDoesNotEchoThePassword(unittest.TestCase):
    def test_the_two_schema_copies_are_identical(self):
        self.assertEqual(SCHEMA_SQL.read_bytes(), (BUILD / "schema" / "postgresql" / "te_core_schema.sql").read_bytes())

    def test_the_password_row_is_captured_not_printed(self):
        text = SCHEMA_SQL.read_text(encoding="utf-8")
        start = text.index("set_config('te.env_label'")
        stmt = text[start:text.index("\\echo", start)]
        self.assertIn("te.app_password", stmt)
        self.assertIn("\\gset", stmt)
        self.assertNotIn(";", stmt, "a ';'-terminated SELECT prints the row, password included")
