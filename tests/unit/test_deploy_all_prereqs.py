"""build/deploy_all.sh: what it does when psql or the server is not there.

A missing psql used to read as "the database does not exist": the script printed a green
"Creating database" and only then failed with `psql: command not found`. A failed existence
query was swallowed the same way (2>/dev/null || true) and also read as "absent". These tests
pin the replacement: real runs check psql and the server up front and say what is wrong, a
failed query is a failure and never an answer, and a --dry-run still needs neither.

The script runs with a restricted PATH that holds only the few utilities it needs, so "psql is
missing" is true even on a machine that has psql, and a stub `psql` plays the server.

Needs bash, so it is marked `tooling` (the Windows job leaves it out).
"""

from __future__ import annotations

import os
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import pytest

try:
    import pty  # not available on Windows; the tests that need a terminal skip there
except ImportError:  # pragma: no cover
    pty = None

pytestmark = pytest.mark.tooling

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "build" / "deploy_all.sh"
BASH = shutil.which("bash") or "bash"

# What the script itself calls (builtins aside).
UTILITIES = ("dirname", "sed", "head", "ls", "sort", "tail", "mktemp", "rm", "uname")

# A stand-in for psql. It logs each call and answers from STUB_* knobs.
PSQL_STUB = r"""#!/usr/bin/env bash
echo "psql $*" >> "$STUB_LOG"
query=""
prev=""
for a in "$@"; do
  [ "$prev" = "-c" ] && query="$a"
  prev="$a"
done
case "$query" in
  "SELECT 1")
    if [ "${STUB_CONNECT:-ok}" = fail ]; then
      echo 'psql: error: connection to server at "localhost" (127.0.0.1), port 5432 failed: Connection refused' >&2
      exit 2
    fi ;;
  *"FROM pg_database"*)
    [ "${STUB_STDERR_WARNING:-0}" = 1 ] && \
      echo "psql: warning: console code page (437) differs from Windows code page (1252)" >&2
    if [ "${STUB_EXISTS_QUERY:-ok}" = fail ]; then
      echo "ERROR:  permission denied for table pg_database" >&2
      exit 2
    fi
    [ "${STUB_DB_EXISTS:-0}" = 1 ] && echo 1 ;;
esac
exit 0
"""


class DeployAllPrereqs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        # The script reads environments/ next to itself.
        (self.dir / "build" / "environments").mkdir(parents=True)
        shutil.copy(SCRIPT, self.dir / "build" / "deploy_all.sh")
        for env in ("dev", "test"):
            (self.dir / "build" / "environments" / f"env_{env}.sql").write_text(
                f"\\set db_name te_mgmt_{env}\n\\set db_owner postgres\n", encoding="utf-8"
            )
        self.log = self.dir / "calls.log"
        self.log.write_text("")

    def _bin(self, with_psql: bool) -> Path:
        path = self.dir / ("bin_psql" if with_psql else "bin_nopsql")
        path.mkdir(exist_ok=True)
        for name in UTILITIES:
            real = shutil.which(name)
            if real and not (path / name).exists():
                (path / name).symlink_to(real)
        if with_psql:
            stub = path / "psql"
            # An absolute shebang: the restricted PATH has no `bash` for `env` to find.
            stub.write_text(PSQL_STUB.replace("#!/usr/bin/env bash", f"#!{BASH}", 1), encoding="utf-8", newline="\n")
            stub.chmod(0o755)
        return path

    def run_script(self, *args: str, with_psql: bool = True, **env: str) -> subprocess.CompletedProcess:
        full = {"PATH": str(self._bin(with_psql)), "STUB_LOG": str(self.log), "HOME": str(self.dir), **env}
        # stdin is closed: with no terminal the script must never wait for an answer, even
        # when the person running pytest has one (stderr is captured, so it is not a terminal).
        return subprocess.run(
            [BASH, str(self.dir / "build" / "deploy_all.sh"), *args],
            capture_output=True,
            text=True,
            env=full,
            timeout=60,
            stdin=subprocess.DEVNULL,
        )

    def run_interactive(self, *args: str, answer: str, **env: str) -> tuple[int, str]:
        """Run the script with a real terminal (a pseudo-terminal) and type ``answer`` at it.

        Returns (exit code, everything the script printed). stdin, stdout and stderr are all
        the terminal, which is what a person at a console gives it.
        """
        full = {"PATH": str(self._bin(True)), "STUB_LOG": str(self.log), "HOME": str(self.dir), **env}
        master, slave = pty.openpty()
        proc = subprocess.Popen(
            [BASH, str(self.dir / "build" / "deploy_all.sh"), *args],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=full,
            close_fds=True,
        )
        os.close(slave)
        out = b""
        try:
            os.write(master, answer.encode())
            deadline = time.monotonic() + 30
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
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
            os.close(master)
        return proc.returncode, out.decode("utf-8", errors="replace")

    @property
    def calls(self) -> list[str]:
        return [c for c in self.log.read_text(encoding="utf-8").splitlines() if c]

    def create_calls(self) -> list[str]:
        return [c for c in self.calls if "CREATE DATABASE" in c]

    def test_the_script_parses(self):
        res = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr)

    # -- psql missing ------------------------------------------------------------

    def test_a_missing_psql_stops_before_touching_anything(self):
        res = self.run_script("dev", with_psql=False, PROGRAMFILES=str(self.dir / "no-pf"))
        self.assertEqual(res.returncode, 1)
        self.assertIn("psql was not found on PATH", res.stderr)
        self.assertNotIn("Creating database", res.stdout, "the old, misleading green line")
        self.assertNotIn("Defence T&E Database Deployment", res.stdout, "stops before the banner")
        self.assertEqual(self.calls, [])

    def test_a_missing_psql_with_an_install_names_the_newest_bin_folder(self):
        pf = self.dir / "pf"
        for version in ("9.6", "16", "18"):
            exe = pf / "PostgreSQL" / version / "bin" / "psql.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("", encoding="utf-8")
        res = self.run_script("dev", with_psql=False, PROGRAMFILES=str(pf))
        self.assertEqual(res.returncode, 1)
        self.assertIn("installed, but its bin folder is not on PATH", res.stderr)
        self.assertIn(
            f'export PATH="{pf}/PostgreSQL/18/bin:$PATH"', res.stderr, "version order, not text order: 18 beats 9.6"
        )

    def test_a_missing_psql_with_no_install_says_how_to_get_it(self):
        res = self.run_script("dev", with_psql=False, PROGRAMFILES=str(self.dir / "empty-pf"))
        self.assertEqual(res.returncode, 1)
        self.assertRegex(res.stderr, r"(?i)install")
        self.assertNotIn("export PATH", res.stderr)
        self.assertNotIn("WSL", res.stderr, "nothing about WSL when this is not WSL")

    # -- bash from PowerShell is WSL: say so, instead of sending a Windows user to apt --------

    def test_inside_wsl_a_missing_psql_points_at_git_bash_not_at_apt_alone(self):
        res = self.run_script(
            "dev", with_psql=False, WSL_DISTRO_NAME="Ubuntu-24.04", PROGRAMFILES=str(self.dir / "empty-pf")
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("psql was not found on PATH", res.stderr)
        self.assertIn("inside WSL", res.stderr)
        self.assertIn("Git Bash", res.stderr)
        self.assertIn(
            r'"C:\Program Files\Git\bin\bash.exe" build/deploy_all.sh',
            res.stderr,
            "the exact PowerShell command to use instead",
        )
        self.assertIn(
            "sudo apt install postgresql-client", res.stderr, "still offered, for a PostgreSQL that runs inside WSL"
        )
        self.assertNotIn("Install it with: apt install", res.stderr, "the generic Linux hint is replaced")
        self.assertNotIn("Creating database", res.stdout)
        self.assertEqual(self.calls, [])

    def test_inside_wsl_with_psql_available_runs_normally(self):
        # A Linux psql inside WSL is a legitimate setup: the message is only for a missing psql.
        res = self.run_script("dev", WSL_DISTRO_NAME="Ubuntu-24.04", STUB_DB_EXISTS="0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("WSL", res.stderr)
        self.assertIn("Succeeded : dev", res.stdout)

    def test_inside_wsl_a_dry_run_still_needs_nothing(self):
        res = self.run_script("--dry-run", "dev", with_psql=False, WSL_DISTRO_NAME="Ubuntu-24.04")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Succeeded : dev", res.stdout)

    def test_a_dry_run_needs_neither_psql_nor_a_server(self):
        res = self.run_script("--dry-run", "dev", with_psql=False)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("Succeeded : dev", res.stdout)

    # -- server unreachable ------------------------------------------------------

    def test_an_unreachable_server_is_reported_once_with_the_reason(self):
        res = self.run_script("dev", "test", STUB_CONNECT="fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Could not connect to PostgreSQL at localhost:5432 as postgres", res.stderr)
        self.assertIn("Connection refused", res.stderr, "psql's own message is passed on")
        self.assertIn("PGPASSWORD", res.stderr)
        self.assertEqual(res.stderr.count("Could not connect"), 1, "once, not once per environment")
        self.assertEqual(self.create_calls(), [])
        self.assertNotIn("Creating database", res.stdout)

    def test_the_host_and_port_in_the_message_are_the_ones_used(self):
        res = self.run_script("dev", STUB_CONNECT="fail", PGHOST="db.example", PGPORT="5433", PGUSER="admin")
        self.assertIn("at db.example:5433 as admin", res.stderr)
        self.assertTrue(
            any("-h db.example" in c and "-p 5433" in c and "-U admin" in c for c in self.calls), self.calls
        )

    # -- the existence check -----------------------------------------------------

    def test_a_failed_existence_query_is_a_failure_not_an_absent_database(self):
        res = self.run_script("dev", STUB_EXISTS_QUERY="fail")
        self.assertEqual(res.returncode, 1)
        self.assertIn("Could not check whether database te_mgmt_dev exists", res.stderr)
        self.assertIn("permission denied", res.stderr)
        self.assertEqual(self.create_calls(), [], "must not try to create what it could not look up")
        self.assertNotIn("Creating database", res.stdout)
        self.assertIn("Failed    : dev", res.stderr)

    def test_a_harmless_stderr_warning_does_not_read_as_the_database_existing(self):
        # Windows psql prints a code-page warning on stderr. If stderr were mixed into the
        # answer it would be non-empty and a missing database would read as present.
        res = self.run_script("dev", STUB_STDERR_WARNING="1", STUB_DB_EXISTS="0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.create_calls()), 1, "the missing database must still be created")
        self.assertNotIn("already exists", res.stdout)

    def test_a_missing_database_is_created_then_deployed(self):
        res = self.run_script("dev", STUB_DB_EXISTS="0")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(len(self.create_calls()), 1)
        self.assertIn("Creating database: te_mgmt_dev", res.stdout)
        self.assertTrue(any("--file=" in c and "env_dev.sql" in c for c in self.calls), self.calls)
        self.assertIn("Succeeded : dev", res.stdout)

    def test_an_existing_database_is_not_recreated(self):
        res = self.run_script("dev", STUB_DB_EXISTS="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.create_calls(), [])
        self.assertIn("already exists", res.stdout)
        self.assertIn("Succeeded : dev", res.stdout)
        self.assertNotIn("[y/N]", res.stdout + res.stderr, "no terminal, so no question")

    # -- an existing database: ask a person, never stop a script ----------------------

    def schema_applied(self) -> bool:
        return any("--file=" in c and "env_dev.sql" in c for c in self.calls)

    def test_yes_uses_an_existing_database_without_asking(self):
        res = self.run_script("--yes", "dev", STUB_DB_EXISTS="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(self.schema_applied(), self.calls)
        self.assertEqual(self.create_calls(), [])
        self.assertIn("Succeeded : dev", res.stdout)

    def test_the_short_yes_flag_is_the_same(self):
        res = self.run_script("-y", "dev", STUB_DB_EXISTS="1")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(self.schema_applied(), self.calls)

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_a_person_is_asked_and_y_uses_the_existing_database(self):
        code, out = self.run_interactive("dev", answer="y\n", STUB_DB_EXISTS="1")
        self.assertEqual(code, 0, out)
        self.assertIn("te_mgmt_dev already exists", out)
        self.assertIn("[y/N]", out, "the question was asked")
        self.assertTrue(self.schema_applied(), self.calls)
        self.assertEqual(self.create_calls(), [])
        self.assertIn("Succeeded : dev", out)

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_n_skips_the_environment_and_changes_nothing(self):
        code, out = self.run_interactive("dev", answer="n\n", STUB_DB_EXISTS="1")
        self.assertEqual(code, 0, "declining is a choice, not a failure: " + out)
        self.assertIn("[y/N]", out)
        self.assertFalse(self.schema_applied(), "the schema must not be applied after a no")
        self.assertEqual(self.create_calls(), [])
        self.assertIn("Skipped", out)
        self.assertNotIn("Succeeded", out, "a skipped environment is not reported as deployed")
        self.assertNotIn("Failed", out)

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_pressing_enter_alone_means_no(self):
        code, out = self.run_interactive("dev", answer="\n", STUB_DB_EXISTS="1")
        self.assertEqual(code, 0, out)
        self.assertFalse(self.schema_applied(), self.calls)
        self.assertIn("Skipped", out)

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_yes_flag_skips_the_question_even_at_a_terminal(self):
        code, out = self.run_interactive("--yes", "dev", answer="", STUB_DB_EXISTS="1")
        self.assertEqual(code, 0, out)
        self.assertNotIn("[y/N]", out)
        self.assertTrue(self.schema_applied(), self.calls)

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_a_missing_database_is_created_without_a_question(self):
        code, out = self.run_interactive("dev", answer="", STUB_DB_EXISTS="0")
        self.assertEqual(code, 0, out)
        self.assertNotIn("[y/N]", out)
        self.assertEqual(len(self.create_calls()), 1)
        self.assertIn("Succeeded : dev", out)

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_a_dry_run_never_asks(self):
        code, out = self.run_interactive("--dry-run", "dev", answer="", STUB_DB_EXISTS="1")
        self.assertEqual(code, 0, out)
        self.assertNotIn("[y/N]", out)
        self.assertEqual(self.calls, [], "a dry run touches nothing, not even psql")

    @unittest.skipIf(pty is None, "needs a pseudo-terminal")
    def test_each_environment_is_asked_about_separately(self):
        # `dev` is accepted and `test` declined: the answers apply one environment at a time.
        code, out = self.run_interactive("dev", "test", answer="y\nn\n", STUB_DB_EXISTS="1")
        self.assertEqual(code, 0, out)
        self.assertTrue(self.schema_applied(), self.calls)
        self.assertFalse(any("--file=" in c and "env_test.sql" in c for c in self.calls), self.calls)
        self.assertIn("Succeeded : dev", out)
        self.assertRegex(out, r"Skipped\s+: test")


if __name__ == "__main__":
    unittest.main()
