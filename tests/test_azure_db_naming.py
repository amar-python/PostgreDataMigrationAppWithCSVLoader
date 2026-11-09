"""#172: Terraform, the deployer and the entrypoint agree on each Azure environment's database.

Before this, three artefacts described production three ways:

  infra/terraform-prod/main.tf   database te_prod          admin pgadmin
  build/deploy_all.sh            database te_mgmt_prod     owner postgres  (hardcoded)
  infra/entrypoint.sh            required a concrete env_prod.sql that nothing in a
                                 freshly built image generates

Decision (3 Nov 2026; names chosen by the product owner 9 Nov 2026): prod, test and
staging use ``te_<env>`` owned by ``pgadmin``, matching their Terraform stacks. Dev stays
``te_mgmt_dev`` owned by ``postgres``: it is local-only and has no stack.
``build/environments/env_<env>.example.sql`` is the single place that says so; the
deployer reads it rather than keeping its own copy.

``AzureArtefactsAgree`` is the regression guard: static, no database, runs in CI's
free-tier job, once per Azure environment. ``EntrypointOnAFreshServer`` is the behavioural
check: it runs the real entrypoint from a tree holding only committed files (what a clean
image contains) against a live server with no pre-existing owner role.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from api.config import settings

ROOT = Path(__file__).resolve().parents[1]
ENV_DIR = ROOT / "build" / "environments"
CANONICAL_OWNER = "pgadmin"
# environment -> its database. Each has an infra/terraform-<env> stack.
AZURE_DATABASES = {"prod": "te_prod", "test": "te_test", "staging": "te_staging"}


def launcher_var(path: Path, name: str) -> str:
    """Value of ``\\set <name> <value>`` in an environment launcher."""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        m = re.match(rf"\\set\s+{name}\s+'?([^'\s]*)'?", line)
        if m:
            return m.group(1)
    raise AssertionError(f"\\set {name} not found in {path}")


def launcher(env: str) -> Path:
    return ENV_DIR / f"env_{env}.example.sql"


def terraform(env: str) -> str:
    return (ROOT / "infra" / f"terraform-{env}" / "main.tf").read_text(encoding="utf-8")


@pytest.mark.unit
class AzureArtefactsAgree(unittest.TestCase):
    deployer = (ROOT / "build" / "deploy_all.sh").read_text(encoding="utf-8")
    entrypoint = (ROOT / "infra" / "entrypoint.sh").read_text(encoding="utf-8")

    def each_env(self):
        for env, db in AZURE_DATABASES.items():
            with self.subTest(env=env):
                yield env, db

    def test_each_launcher_names_the_canonical_database_and_owner(self):
        for env, db in self.each_env():
            self.assertEqual(launcher_var(launcher(env), "db_name"), db)
            self.assertEqual(launcher_var(launcher(env), "db_owner"), CANONICAL_OWNER)

    def test_dev_is_unchanged_and_local_only(self):
        self.assertEqual(launcher_var(launcher("dev"), "db_name"), "te_mgmt_dev")
        self.assertEqual(launcher_var(launcher("dev"), "db_owner"), "postgres")

    def test_terraform_creates_the_same_database(self):
        for env, _ in self.each_env():
            names = re.findall(
                r'resource\s+"azurerm_postgresql_flexible_server_database"\s+"\w+"\s*\{[^}]*?name\s*=\s*"([^"]+)"',
                terraform(env))
            self.assertEqual(names, [launcher_var(launcher(env), "db_name")],
                             "Terraform's database differs from the one the deployer will deploy to")

    def test_terraform_admin_is_the_launchers_owner(self):
        for env, _ in self.each_env():
            admin = re.search(r'administrator_login\s*=\s*"([^"]+)"', terraform(env)).group(1)
            self.assertEqual(admin, launcher_var(launcher(env), "db_owner"))

    def test_the_migration_job_runs_as_that_owner_against_that_database(self):
        for env, _ in self.each_env():
            tf = terraform(env)
            job_user = re.search(r'name\s*=\s*"PGUSER"\s*value\s*=\s*"([^"]+)"', tf).group(1)
            self.assertEqual(job_user, launcher_var(launcher(env), "db_owner"))
            self.assertRegex(tf, r'name\s*=\s*"PGDATABASE"\s*value\s*=\s*azurerm_postgresql_flexible_server_database\.\w+\.name',
                             "PGDATABASE must come from the database resource, not a second literal")

    def test_the_migration_job_is_given_the_app_role_password(self):
        """Without it entrypoint.sh refuses to deploy, so a first run would fail."""
        for env, _ in self.each_env():
            tf = terraform(env)
            self.assertRegex(tf, r'name\s*=\s*"APP_USER_PASSWORD"\s*secret_name\s*=\s*"app-user-password"')
            self.assertRegex(tf, r'name\s*=\s*"app-user-password"[^}]*azurerm_key_vault_secret\.app_user_password\.id')

    def test_every_launcher_declares_both_so_the_deployer_can_read_them(self):
        for env in ("dev", "test", "staging", "prod"):
            with self.subTest(env=env):
                self.assertTrue(launcher_var(launcher(env), "db_name"), launcher(env))
                self.assertTrue(launcher_var(launcher(env), "db_owner"), launcher(env))

    def test_the_deployer_keeps_no_name_or_owner_of_its_own(self):
        """The hardcoded copies are what drifted."""
        code = "\n".join(l for l in self.deployer.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotRegex(code, r"te_mgmt_", "deploy_all.sh hardcodes a database name")
        self.assertNotRegex(code, r"OWNER\s*=\s*postgres", "deploy_all.sh hardcodes the database owner")

    def test_the_entrypoint_generates_its_launcher_from_the_committed_template(self):
        self.assertIn("example.sql", self.entrypoint,
                      "entrypoint.sh must build env_<env>.sql from the template; a clean image has only the template")

    def test_no_template_is_a_populated_launcher(self):
        """RV-S4 (#174): the fix must not bake a real password into the image."""
        for env in ("dev", "test", "staging", "prod"):
            with self.subTest(env=env):
                self.assertEqual(launcher_var(launcher(env), "app_password"), "__INJECT_AT_DEPLOY__")


@pytest.mark.integration
class EntrypointOnAFreshServer(unittest.TestCase):
    """Run the real entrypoint, from committed files only, against a live server.

    The launcher's database, schema, owner and app user are rewritten to throwaway
    names so the run cannot touch a real environment; the machinery under test (name
    and owner read from the launcher, launcher generated at runtime, owner role
    created when absent) is identical. The names themselves are pinned by
    ``AzureArtefactsAgree``.
    """

    PASSWORD = "a'b\\c&d/e\"f g"  # every character the generation step must survive

    @classmethod
    def setUpClass(cls):
        tag = uuid.uuid4().hex[:8]
        cls.db, cls.schema = f"te_ept_{tag}", f"ept_{tag}"
        cls.owner, cls.app_user = f"ept_owner_{tag}", f"ept_app_{tag}"
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        tracked = subprocess.run(["git", "ls-files", "--", "build", "infra/entrypoint.sh"], cwd=ROOT,
                                 capture_output=True, text=True, check=True).stdout.split()
        for rel in tracked:  # committed files only: what a clean image holds
            dest = cls.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dest)
        shutil.copy2(ROOT / "infra" / "entrypoint.sh", cls.root / "entrypoint.sh")
        tpl = cls.root / "build" / "environments" / "env_prod.example.sql"
        text = tpl.read_text(encoding="utf-8-sig")
        for var, value in (("db_name", cls.db), ("schema_name", cls.schema),
                           ("db_owner", cls.owner), ("app_user", cls.app_user)):
            text = re.sub(rf"(\\set\s+{var}\s+)\S+", rf"\g<1>{value}", text)
        tpl.write_text(text, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        conn = cls._admin()
        try:
            conn.autocommit = True  # DROP DATABASE cannot run in a transaction
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(cls.db)))
                for role in (cls.app_user, cls.owner):
                    cur.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
        finally:
            conn.close()
            cls.tmp.cleanup()

    @staticmethod
    def _admin():
        return psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=settings.PG_USER,
                                password=settings.PG_PASSWORD, dbname="postgres")

    def _entrypoint(self, **extra):
        env = {k: v for k, v in os.environ.items() if k != "APP_USER_PASSWORD"}
        env.update(MIGRATION_ROOT=str(self.root), TARGET_ENV="prod", PGHOST=settings.PG_HOST,
                   PGPORT=str(settings.PG_PORT), PGUSER=settings.PG_USER, PGPASSWORD=settings.PG_PASSWORD,
                   PGDATABASE=self.db, WAIT_FOR_DB_SECONDS="10")
        env.update(extra)
        return subprocess.run(["bash", str(self.root / "entrypoint.sh"), "deploy"], env=env,
                              capture_output=True, text=True, timeout=300)

    def test_1_it_refuses_to_deploy_without_a_password_and_says_why(self):
        run = self._entrypoint()
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("APP_USER_PASSWORD", run.stderr, run.stderr)
        self.assertFalse((self.root / "build" / "environments" / "env_prod.sql").exists())

    def test_2_it_refuses_a_job_pointed_at_a_different_database(self):
        run = self._entrypoint(APP_USER_PASSWORD=self.PASSWORD, PGDATABASE="somewhere_else")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn(self.db, run.stderr, run.stderr)

    def test_3_a_clean_tree_deploys_to_the_launchers_database_and_owner(self):
        self.assertFalse((self.root / "build" / "environments" / "env_prod.sql").exists(),
                         "the tree must start with only the template, like a clean image")
        run = self._entrypoint(APP_USER_PASSWORD=self.PASSWORD)
        self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-1500:])
        with self._admin() as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (self.db,))
            row = cur.fetchone()
            self.assertIsNotNone(row, f"database {self.db} was not created")
            self.assertEqual(row[0], self.owner, "database owner is not the launcher's db_owner")
            cur.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (self.owner,))
            self.assertEqual(cur.fetchone(), (False,), "the owner role must exist and be NOLOGIN")
        with psycopg2.connect(host=settings.PG_HOST, port=settings.PG_PORT, user=self.app_user,
                              password=self.PASSWORD, dbname=self.db) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s", (self.schema,))
            self.assertGreaterEqual(cur.fetchone()[0], 12, "the T&E tables were not created")

    def test_4_no_launcher_with_a_password_is_left_behind(self):
        self.assertFalse((self.root / "build" / "environments" / "env_prod.sql").exists(),
                         "the generated launcher holds the app password and must be removed")

    def test_5_a_second_run_is_idempotent(self):
        run = self._entrypoint(APP_USER_PASSWORD=self.PASSWORD)
        self.assertEqual(run.returncode, 0, run.stdout[-1500:] + run.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
