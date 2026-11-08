"""Shared contract every deployed environment must satisfy."""
from __future__ import annotations
import shutil, subprocess  # nosec B404

CORE_TABLES = {
    "organisations", "personnel", "test_programs", "temp_documents",
    "test_phases", "requirements", "test_cases", "vcrm_entries",
    "test_events", "test_results", "defect_reports", "evidence_artifacts",
}
SEEDED_TABLES = ("organisations", "personnel", "requirements")
HELP = ("Deploy environments first:\n"
        "    bash scripts/provision_full_test_env.sh")


def _psql(db, sql):
    if shutil.which("psql") is None:
        return False, "psql not on PATH"
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["psql", "-d", db, "-tA", "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-c", sql],
            capture_output=True, text=True, timeout=20)
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, str(exc)
    return proc.returncode == 0, proc.stdout.strip()


class EnvironmentContract:
    ENV = ""; DB = ""; SCHEMA = ""; APP_USER = ""; CONN_LIMIT = 0; SEEDED = False

    @classmethod
    def setUpClass(cls):
        ok, out = _psql(cls.DB, "SELECT 1")
        if not ok:
            raise AssertionError(f"Environment '{cls.ENV}' not reachable (db='{cls.DB}').\n{out[:200]}\n{HELP}")

    def test_database_exists(self):
        ok, out = _psql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{self.DB}'")
        self.assertTrue(ok, out); self.assertEqual(out, "1")

    def test_schema_has_all_core_tables(self):
        ok, out = _psql(self.DB, f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{self.SCHEMA}'")
        self.assertTrue(ok, out)
        missing = sorted(CORE_TABLES - set(out.splitlines()))
        self.assertEqual(missing, [], f"{self.ENV}: missing tables {missing}")

    def test_application_role_exists(self):
        ok, out = _psql(self.DB, f"SELECT 1 FROM pg_roles WHERE rolname = '{self.APP_USER}'")
        self.assertTrue(ok, out); self.assertEqual(out, "1")

    def test_application_role_connection_limit(self):
        ok, out = _psql(self.DB, f"SELECT COALESCE(rolconnlimit,-999) FROM pg_roles WHERE rolname = '{self.APP_USER}'")
        self.assertTrue(ok, out)
        self.assertEqual(int(out), self.CONN_LIMIT, f"{self.ENV}: expected {self.CONN_LIMIT}, got {out}")

    def test_seed_data_matches_policy(self):
        """Staging and prod must never be seeded."""
        for table in SEEDED_TABLES:
            with self.subTest(table=table):
                ok, out = _psql(self.DB, f"SELECT COUNT(*) FROM {self.SCHEMA}.{table}")
                self.assertTrue(ok, out)
                count = int(out)
                if self.SEEDED:
                    self.assertGreater(count, 0, f"{self.ENV}: seeded but {table} is empty")
                else:
                    self.assertEqual(count, 0, f"{self.ENV} must NOT be seeded — {table} has {count} rows")
