"""scripts/create_tenant_admin.py when the tenant or the username already exists.

Running it twice used to end in a psycopg2 UniqueViolation traceback, after the person had
already typed a password. It now says what exists and, for a tenant that is already there,
asks whether to use it (or uses it without asking when --use-existing is given). Declining,
having no terminal, or an unusable username changes nothing.

The script is run as its own process against a live PostgreSQL, as a person would run it, and
the results are read back from the database. The questions are answered through a real
pseudo-terminal. These tests fail, never skip, without a database.
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql

from api.config import settings
from api.services import accounts
from api.tenancy import schema_for

try:
    import pty  # not available on Windows; the tests that need a terminal skip there
except ImportError:  # pragma: no cover
    pty = None

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "create_tenant_admin.py"
PASSWORD = "correct horse battery staple"
OTHER_PASSWORD = "a completely different passphrase"


def _connect():
    return psycopg2.connect(
        host=settings.PG_HOST,
        port=settings.PG_PORT,
        user=settings.PG_USER,
        password=settings.PG_PASSWORD.get_secret_value(),
        dbname=settings.PG_DATABASE,
    )


@pytest.mark.integration
class CreateTenantAdmin(unittest.TestCase):
    def setUp(self):
        tag = f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
        self.tenant, self.user, self.new_user = f"ct_{tag}", f"cu_{tag}", f"cn_{tag}"
        self.addCleanup(self._cleanup)

    # -- helpers ---------------------------------------------------------------------

    def _env(self, password: str | None = PASSWORD) -> dict:
        env = {k: v for k, v in os.environ.items() if k != "TE_ADMIN_PASSWORD"}
        if password is not None:
            env["TE_ADMIN_PASSWORD"] = password
        return env

    def run_script(self, *args: str, password: str | None = PASSWORD) -> subprocess.CompletedProcess:
        """No terminal: stdin is closed, and stderr is captured so it is not one either."""
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            env=self._env(password),
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )

    def run_interactive(self, *args: str, answer: str, password: str | None = PASSWORD) -> tuple[int, str]:
        """Run the script with a pseudo-terminal and type ``answer`` at it."""
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            env=self._env(password),
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        out = b""
        try:
            os.write(master, answer.encode())
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.5)
                if ready:
                    try:
                        chunk = os.read(master, 4096)
                    except OSError:  # the terminal closed: the script has finished
                        break
                    if not chunk:
                        break
                    out += chunk
                elif proc.poll() is not None:
                    break
            proc.wait(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
            os.close(master)
        return proc.returncode, out.decode("utf-8", errors="replace")

    def create(
        self, *extra: str, user: str | None = None, tenant: str | None = None, password: str = PASSWORD
    ) -> subprocess.CompletedProcess:
        res = self.run_script(
            "--tenant",
            tenant or self.tenant,
            "--name",
            "Original name",
            "--username",
            user or self.user,
            *extra,
            password=password,
        )
        return res

    def _q(self, query: str, *params):
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(sql.SQL(query).format(c=sql.Identifier(settings.CONTROL_SCHEMA)), params)
            return cur.fetchall() if cur.description else None

    def existing(self, tenant: str | None = None, user: str | None = None) -> accounts.Existing:
        with _connect() as conn, conn.cursor() as cur:
            return accounts.existing(cur, tenant or self.tenant, user or self.user)

    def password_hash(self, user: str) -> str | None:
        rows = self._q("SELECT password_hash FROM {c}.users WHERE username = %s", user)
        return rows[0][0] if rows else None

    def role(self, tenant: str, user: str) -> str | None:
        rows = self._q(
            "SELECT m.role FROM {c}.memberships m JOIN {c}.users u ON u.id = m.user_id "
            "JOIN {c}.tenants t ON t.id = m.tenant_id WHERE t.slug = %s AND u.username = %s",
            tenant,
            user,
        )
        return rows[0][0] if rows else None

    def tenant_name(self, tenant: str) -> str | None:
        rows = self._q("SELECT name FROM {c}.tenants WHERE slug = %s", tenant)
        return rows[0][0] if rows else None

    def can_sign_in(self, tenant: str, user: str, password: str) -> bool:
        with _connect() as conn, conn.cursor() as cur:
            result = accounts.login(cur, tenant, user, password)
            conn.rollback()  # do not leave a session behind
            return result is not None

    def _cleanup(self):
        try:
            with _connect() as conn, conn.cursor() as cur:
                names = [self.user, self.new_user]
                cur.execute(
                    sql.SQL(
                        "DELETE FROM {c}.sessions WHERE user_id IN (SELECT id FROM {c}.users WHERE username = ANY(%s))"
                    ).format(c=sql.Identifier(settings.CONTROL_SCHEMA)),
                    (names,),
                )
                cur.execute(
                    sql.SQL(
                        "DELETE FROM {c}.memberships WHERE user_id IN "
                        "(SELECT id FROM {c}.users WHERE username = ANY(%s))"
                    ).format(c=sql.Identifier(settings.CONTROL_SCHEMA)),
                    (names,),
                )
                cur.execute(
                    sql.SQL("DELETE FROM {c}.users WHERE username = ANY(%s)").format(
                        c=sql.Identifier(settings.CONTROL_SCHEMA)
                    ),
                    (names,),
                )
                cur.execute(
                    sql.SQL("DELETE FROM {c}.tenants WHERE slug = %s").format(
                        c=sql.Identifier(settings.CONTROL_SCHEMA)
                    ),
                    (self.tenant,),
                )
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(self.tenant))))
        except psycopg2.Error:
            pass  # best effort: a leftover test tenant is harmless, and a failed cleanup must not mask a result

    # -- a tenant that does not exist yet --------------------------------------------

    def test_a_new_tenant_and_admin_are_created(self):
        res = self.create()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"Created tenant '{self.tenant}'", res.stdout)
        self.assertEqual(self.role(self.tenant, self.user), "tenant_admin")
        self.assertTrue(self.can_sign_in(self.tenant, self.user, PASSWORD))

    def test_a_short_password_is_refused_before_the_database_is_touched(self):
        res = self.create(password="too short")
        self.assertEqual(res.returncode, 2, res.stderr)
        self.assertIn("at least 12 characters", res.stderr)
        self.assertEqual(self.existing(), accounts.Existing(False, False, False))

    # -- the tenant exists, nobody asked --------------------------------------------

    def seed(self):
        res = self.create()
        self.assertEqual(res.returncode, 0, res.stderr)
        return self.password_hash(self.user)

    def test_running_it_twice_without_a_terminal_stops_cleanly_and_changes_nothing(self):
        before = self.seed()
        res = self.create(password=OTHER_PASSWORD)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertNotIn("UniqueViolation", res.stderr)
        self.assertIn("already exists", res.stderr)
        self.assertIn("--use-existing", res.stderr, "it says how to proceed")
        self.assertEqual(self.password_hash(self.user), before, "the existing account is untouched")

    def test_use_existing_accepts_a_member_that_is_already_there_and_keeps_its_password(self):
        before = self.seed()
        # No password is supplied or typed: nothing is created, so nothing asks for one.
        res = self.create("--use-existing", password=None)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Traceback", res.stderr)
        self.assertIn("Using the existing tenant", res.stdout)
        self.assertIn("reset_password.py", res.stdout, "it points at the way to a new password")
        self.assertEqual(self.password_hash(self.user), before)
        self.assertTrue(self.can_sign_in(self.tenant, self.user, PASSWORD))

    def test_use_existing_adds_a_new_admin_to_an_existing_tenant(self):
        self.seed()
        res = self.create("--use-existing", user=self.new_user, password=OTHER_PASSWORD)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"Added tenant admin '{self.new_user}'", res.stdout)
        self.assertEqual(self.role(self.tenant, self.new_user), "tenant_admin")
        self.assertTrue(self.can_sign_in(self.tenant, self.new_user, OTHER_PASSWORD))
        self.assertTrue(self.can_sign_in(self.tenant, self.user, PASSWORD), "the first admin is unaffected")
        self.assertEqual(self.tenant_name(self.tenant), "Original name", "an existing tenant is not renamed")

    def test_a_new_admin_for_an_existing_tenant_is_not_added_unless_accepted(self):
        self.seed()
        res = self.create(user=self.new_user, password=OTHER_PASSWORD)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("--use-existing", res.stderr)
        self.assertEqual(
            self.existing(user=self.new_user), accounts.Existing(True, False, False), "no account was created"
        )

    def test_use_existing_does_not_apply_to_a_tenant_that_does_not_exist(self):
        res = self.create("--use-existing")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn(f"Created tenant '{self.tenant}'", res.stdout, "a new tenant is simply created")

    # -- a username that belongs to someone else --------------------------------------

    def test_a_username_that_belongs_to_another_tenant_is_never_reused(self):
        self.seed()
        other_tenant = f"{self.tenant}_o"
        self.addCleanup(self._drop_tenant, other_tenant)
        for flag in ((), ("--use-existing",)):
            with self.subTest(flag=flag):
                res = self.create(*flag, tenant=other_tenant)  # same username, a tenant it is not in
                self.assertEqual(res.returncode, 1, res.stderr)
                self.assertIn("already in use", res.stderr)
                self.assertNotIn("Traceback", res.stderr)
                self.assertIsNone(self.role(other_tenant, self.user), "it was not made an admin there")

    def test_a_username_in_use_is_refused_even_when_the_tenant_exists_and_is_accepted(self):
        self.seed()
        second = f"{self.tenant}_2"
        self.addCleanup(self._drop_tenant, second)
        self.assertEqual(self.create(user=self.new_user, tenant=second, password=OTHER_PASSWORD).returncode, 0)
        # self.user is not a member of `second`, and `second` exists.
        res = self.create("--use-existing", tenant=second)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("already in use", res.stderr)
        self.assertIsNone(self.role(second, self.user))

    def _drop_tenant(self, slug: str):
        try:
            with _connect() as conn, conn.cursor() as cur:
                names = [self.user, self.new_user]
                for stmt in (
                    "DELETE FROM {c}.sessions WHERE tenant_id IN (SELECT id FROM {c}.tenants WHERE slug = %s)",
                    "DELETE FROM {c}.memberships WHERE tenant_id IN (SELECT id FROM {c}.tenants WHERE slug = %s)",
                ):
                    cur.execute(sql.SQL(stmt).format(c=sql.Identifier(settings.CONTROL_SCHEMA)), (slug,))
                cur.execute(
                    sql.SQL(
                        "DELETE FROM {c}.users WHERE username = ANY(%s) AND NOT EXISTS "
                        "(SELECT 1 FROM {c}.memberships m WHERE m.user_id = {c}.users.id)"
                    ).format(c=sql.Identifier(settings.CONTROL_SCHEMA)),
                    (names,),
                )
                cur.execute(
                    sql.SQL("DELETE FROM {c}.tenants WHERE slug = %s").format(
                        c=sql.Identifier(settings.CONTROL_SCHEMA)
                    ),
                    (slug,),
                )
                cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_for(slug))))
        except psycopg2.Error:
            pass

    # -- a person at the terminal -----------------------------------------------------

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_a_person_is_asked_and_y_uses_the_existing_tenant(self):
        before = self.seed()
        code, out = self.run_interactive(
            "--tenant", self.tenant, "--name", "Original name", "--username", self.user, answer="y\n", password=None
        )
        self.assertEqual(code, 0, out)
        self.assertIn("already exists", out)
        self.assertIn("[y/N]", out, "the question was asked")
        self.assertIn("Using the existing tenant", out)
        self.assertNotIn("Traceback", out)
        self.assertEqual(self.password_hash(self.user), before)

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_n_changes_nothing(self):
        before = self.seed()
        code, out = self.run_interactive(
            "--tenant",
            self.tenant,
            "--name",
            "Original name",
            "--username",
            self.new_user,
            answer="n\n",
            password=OTHER_PASSWORD,
        )
        self.assertEqual(code, 1, out)
        self.assertIn("[y/N]", out)
        self.assertIn("Nothing was changed", out)
        self.assertEqual(self.existing(user=self.new_user), accounts.Existing(True, False, False))
        self.assertEqual(self.password_hash(self.user), before)

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_pressing_enter_alone_means_no(self):
        self.seed()
        code, out = self.run_interactive(
            "--tenant",
            self.tenant,
            "--name",
            "Original name",
            "--username",
            self.new_user,
            answer="\n",
            password=OTHER_PASSWORD,
        )
        self.assertEqual(code, 1, out)
        self.assertEqual(self.existing(user=self.new_user), accounts.Existing(True, False, False))

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_y_adds_a_new_admin_to_the_existing_tenant(self):
        self.seed()
        code, out = self.run_interactive(
            "--tenant",
            self.tenant,
            "--name",
            "Original name",
            "--username",
            self.new_user,
            answer="yes\n",
            password=OTHER_PASSWORD,
        )
        self.assertEqual(code, 0, out)
        self.assertIn("add", out.lower())
        self.assertEqual(self.role(self.tenant, self.new_user), "tenant_admin")
        self.assertTrue(self.can_sign_in(self.tenant, self.new_user, OTHER_PASSWORD))

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_a_new_tenant_is_created_without_a_question(self):
        code, out = self.run_interactive(
            "--tenant", self.tenant, "--name", "Original name", "--username", self.user, answer=""
        )
        self.assertEqual(code, 0, out)
        self.assertNotIn("[y/N]", out)
        self.assertIn(f"Created tenant '{self.tenant}'", out)


if __name__ == "__main__":
    unittest.main()
