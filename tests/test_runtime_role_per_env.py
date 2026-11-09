"""RV-S3 (#173): each environment gets its own runtime role and credential file.

Before this fix the runtime role was the cluster-wide ``te_app``, with its
password in a single ``~/.te-migration/app-db.env``. Dev PCs commonly run one
PostgreSQL cluster for several environments, so provisioning the second one
rotated the one role's password and overwrote the one file, and the first
environment's connections failed on their next reconnect. Reproduced on
PostgreSQL 16 with password authentication:

    $ PGDATABASE=te_mgmt_dev  python scripts/create_app_role.py   # main's version
    Role 'te_app' is ready (created).
    $ psql -U te_app -d te_mgmt_dev -c "select 'DEV OK'"          # Dev's own password
    DEV OK
    $ PGDATABASE=te_mgmt_test python scripts/create_app_role.py
    Role 'te_app' is ready (new password set).
    $ psql -U te_app -d te_mgmt_dev -c "select 'DEV OK'"          # same password
    FATAL:  password authentication failed for user "te_app"

Two layers of cover here:

``PerEnvironmentNaming`` is a unit test and the actual regression guard -- it
pins the derivation that makes the names distinct, needs no database, and so
runs in CI's free-tier job on every push.

``ProvisioningOneEnvironmentLeavesAnotherAlone`` is the end-to-end
reproduction the issue asks for: it provisions two environments against a live
cluster through the real script and asserts the first one's credentials still
work afterwards.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from api.config import settings
from scripts.create_app_role import (
    ENVIRONMENTS,
    LEGACY_ENV_FILE,
    LEGACY_ROLE,
    env_file_for,
    role_for,
)

_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
class PerEnvironmentNaming(unittest.TestCase):
    """The role name and credential file must both be derived from --env."""

    def test_every_environment_gets_a_distinct_role(self):
        roles = [role_for(env) for env in ENVIRONMENTS]
        self.assertEqual(len(set(roles)), len(ENVIRONMENTS), f"roles collide across environments: {roles}")

    def test_every_environment_gets_a_distinct_credential_file(self):
        files = [env_file_for(env) for env in ENVIRONMENTS]
        self.assertEqual(len(set(files)), len(ENVIRONMENTS), f"credential files collide: {files}")

    def test_no_environment_reuses_the_pre_fix_names(self):
        """The cluster-wide names are what made provisioning cross-contaminate."""
        for env in ENVIRONMENTS:
            self.assertNotEqual(role_for(env), LEGACY_ROLE,
                                f"--env {env} still resolves to the shared role {LEGACY_ROLE}")
            self.assertNotEqual(env_file_for(env), LEGACY_ENV_FILE,
                                f"--env {env} still resolves to the shared file {LEGACY_ENV_FILE}")

    def test_env_is_mandatory(self):
        """Without --env the script must refuse, not fall back to a shared default."""
        run = subprocess.run([sys.executable, "scripts/create_app_role.py"],
                             cwd=_ROOT, capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0, "the script ran without --env")
        self.assertIn("--env", run.stderr, run.stderr)

    def test_an_unknown_environment_is_refused(self):
        run = subprocess.run([sys.executable, "scripts/create_app_role.py", "--env", "producton"],
                             cwd=_ROOT, capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0, "a misspelled environment was accepted")


@pytest.mark.unit
class UpgradingAPreFixDevPC(unittest.TestCase):
    """A dev PC that already has ~/.te-migration/app-db.env must upgrade cleanly.

    start-api.ps1 still reads the legacy file as a fallback, so leaving it in
    place would let the API keep starting on the old cluster-wide role's
    credentials -- the stale-credential half of #173. Provisioning moves it
    aside instead. The real path is patched out so the test cannot touch the
    developer's own home directory.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.legacy = Path(self.tmp.name) / "app-db.env"

    def _retire(self, env: str):
        with unittest.mock.patch("scripts.create_app_role.LEGACY_ENV_FILE", self.legacy):
            from scripts.create_app_role import retire_legacy_credentials
            return retire_legacy_credentials(env)

    def test_a_legacy_file_is_moved_aside_and_kept(self):
        self.legacy.write_text("APP_DB_USER=te_app\nAPP_DB_PASSWORD=old-secret\n", encoding="utf-8")
        moved = self._retire("dev")
        self.assertIsNotNone(moved, "the legacy credential file was left in place")
        self.assertFalse(self.legacy.exists(), "start-api.ps1 would still read the legacy file")
        self.assertTrue(Path(moved).exists(), "the legacy file was deleted rather than moved aside")
        self.assertIn("te_app", Path(moved).read_text(),
                      "the move must preserve the file, so it can be put back with one mv")

    def test_a_clean_dev_pc_is_untouched(self):
        self.assertIsNone(self._retire("dev"), "reported a migration where there was no legacy file")

    def test_retiring_twice_is_idempotent(self):
        self.legacy.write_text("APP_DB_USER=te_app\n", encoding="utf-8")
        self._retire("dev")
        self.assertIsNone(self._retire("dev"), "a second run must find nothing left to move")


@pytest.mark.integration
class ProvisioningOneEnvironmentLeavesAnotherAlone(unittest.TestCase):
    """Provision env A, then env B on the same cluster; A must still connect.

    This is the reproduction from the issue. ``--env-file`` is pointed at a temp
    directory so the run cannot touch the developer's own ``~/.te-migration``;
    the role names still come from ``--env``, which is what keeps the two
    environments apart. ``PerEnvironmentNaming`` covers the file naming.
    """

    FIRST, SECOND = "test", "staging"

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.provisioned: list[str] = []
        for env in (cls.FIRST, cls.SECOND):
            if cls._role_exists(role_for(env)):
                raise unittest.SkipTest(
                    f"role {role_for(env)} already exists on this server. Re-provisioning it would "
                    "reset the password of a role that may be in use here, so this test declines to "
                    "run. On a clean server (CI) it runs."
                )
        for env in (cls.FIRST, cls.SECOND):
            cls.credentials(env)  # provisions, in order: FIRST then SECOND
            cls.provisioned.append(role_for(env))

    @classmethod
    def tearDownClass(cls):
        for role in cls.provisioned:
            with cls._owner() as conn, conn.cursor() as cur:
                cur.execute(sql.SQL("DROP OWNED BY {r}; DROP ROLE {r}").format(r=sql.Identifier(role)))
                conn.commit()
        cls.tmp.cleanup()

    @staticmethod
    def _owner():
        return psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.PG_USER,
                                password=settings.PG_PASSWORD, dbname=settings.PG_DATABASE)

    @classmethod
    def _role_exists(cls, role: str) -> bool:
        with cls._owner() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            return cur.fetchone() is not None

    @classmethod
    def credentials(cls, env: str) -> dict[str, str]:
        """Run the real script for one environment and return what it wrote."""
        path = Path(cls.tmp.name) / f"app-db-{env}.env"
        if not path.exists():
            run = subprocess.run(
                [sys.executable, "scripts/create_app_role.py", "--env", env, "--env-file", str(path)],
                cwd=_ROOT, capture_output=True, text=True)
            assert run.returncode == 0, run.stderr
        return dict(line.split("=", 1) for line in path.read_text().splitlines())

    def _connect_as(self, creds: dict[str, str]):
        return psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT,
                                user=creds["APP_DB_USER"], password=creds["APP_DB_PASSWORD"],
                                dbname=settings.PG_DATABASE)

    def test_the_two_environments_got_different_roles(self):
        self.assertNotEqual(self.credentials(self.FIRST)["APP_DB_USER"],
                            self.credentials(self.SECOND)["APP_DB_USER"],
                            "both environments were given the same role, so provisioning one "
                            "rotates the other's password (RV-S3, #173)")

    def test_the_first_environments_credentials_still_work(self):
        """The regression: this failed once the second environment was provisioned."""
        creds = self.credentials(self.FIRST)
        try:
            with self._connect_as(creds) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                self.assertEqual(cur.fetchone()[0], 1)
        except psycopg2.OperationalError as exc:
            self.fail(
                f"{self.FIRST}'s stored credentials stopped working after {self.SECOND} was "
                f"provisioned on the same cluster: {exc}"
            )

    def test_the_second_environments_credentials_work_too(self):
        creds = self.credentials(self.SECOND)
        with self._connect_as(creds) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            self.assertEqual(cur.fetchone()[0], 1)

    def test_the_credential_files_are_owner_readable_only(self):
        """Unchanged from M3d, re-asserted because the write path moved."""
        import os
        if os.name != "posix":
            self.skipTest("file modes are a POSIX concern")
        for env in (self.FIRST, self.SECOND):
            path = Path(self.tmp.name) / f"app-db-{env}.env"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, f"{path} is not 0600")


if __name__ == "__main__":
    unittest.main()
