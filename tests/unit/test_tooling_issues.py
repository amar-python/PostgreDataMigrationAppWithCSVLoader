"""Regression tests for closed tooling, CI and docs issues.

  #171  setup.sh must not destroy the prior config.local.env when writing a new one fails
  #180  every psql call in the evals runner stops at the first SQL error
  #181  the SQL test wrapper must fail an environment whose assertions failed
  #182  the offline bundle build must stop when a package download fails
  #130  the frontend lock file must match package.json
  #169  docs/TEST_CASES.md must be up to date with the tests
  #194  the coverage-floor gate must fail below a floor
  #207  API_INTEGRATION.md must defer to the generated schema, and the schema must be served

No database needed. Shell blocks are cut out of the real scripts and run, not re-implemented here;
those classes are marked `tooling` (they need bash), so the Windows job leaves them out.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # tests/unit/ -> repo root


def _between(text: str, start: str, end: str, *, include_end: bool = False) -> str:
    i = text.index(start)
    j = text.index(end, i)
    return text[i:j + (len(end) if include_end else 0)]


def _bash(script: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                          env={**os.environ, **env}, timeout=60)


# ── #171 ─────────────────────────────────────────────────────────────────────

@pytest.mark.tooling
class SetupKeepsPriorConfigOnFailure(unittest.TestCase):
    """#171: the config is written to a temp file and moved into place only once complete."""

    BLOCK = _between((ROOT / "build/setup.sh").read_text(encoding="utf-8"),
                     '_config_tmp="${CONFIG_LOCAL}.new"', 'mv -f "$_config_tmp" "$CONFIG_LOCAL"', include_end=True)
    VARS = sorted(set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)\}", BLOCK)) - {"CONFIG_LOCAL"})

    def _run(self, omit: str | None):
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / "config.local.env"
            config.write_text("PRIOR=keep-me\n")
            exports = "".join(f'{v}=x; ' for v in self.VARS if v != omit)
            script = f'set -euo pipefail; error(){{ echo "$@" >&2; }}; CONFIG_LOCAL="{config}"; {exports}\n{self.BLOCK}\n'
            res = _bash(script)
            return res, config.read_text(), sorted(p.name for p in Path(d).iterdir())

    def test_the_block_was_found_and_uses_many_variables(self):
        self.assertGreater(len(self.VARS), 30)

    def test_success_replaces_the_config_and_leaves_no_temp_file(self):
        res, content, files = self._run(omit=None)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("PRIOR=keep-me", content)
        self.assertIn("PG_PORT=x", content)
        self.assertEqual(files, ["config.local.env"])

    def test_an_unset_variable_fails_the_run_but_keeps_the_prior_config(self):
        res, content, files = self._run(omit="PG_PORT")
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(content, "PRIOR=keep-me\n")
        self.assertEqual(files, ["config.local.env"], "the temp file must be cleaned up")


# ── #180 ─────────────────────────────────────────────────────────────────────

def _psql_calls(function: str | None = None) -> list[str]:
    tree = ast.parse((ROOT / "evals/runner.py").read_text(encoding="utf-8"))
    scope = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function] if function else [tree]
    return [ast.unparse(n) for root in scope for n in ast.walk(root)
            if isinstance(n, ast.List) and n.elts and isinstance(n.elts[0], ast.Constant) and n.elts[0].value == "psql"]


@pytest.mark.unit
class EvalRunnerStopsOnSqlErrors(unittest.TestCase):
    def test_the_idempotency_eval_stops_at_the_first_sql_error(self):
        calls = _psql_calls("_run_deploy_dev_twice")  # #180
        self.assertTrue(calls, "the idempotency eval's psql call was not found")
        for call in calls:
            self.assertIn("ON_ERROR_STOP=1", call)


# ── #181 ─────────────────────────────────────────────────────────────────────

@pytest.mark.tooling
class SqlWrapperFailsOnAssertionFailures(unittest.TestCase):
    """#181: psql exits 0 even when assertions record FAIL rows; the wrapper must read the output."""

    BLOCK = _between((ROOT / "tests/run_tests.sh").read_text(encoding="utf-8"),
                     "if grep -qiE 'FAIL|TEST\\(S\\) FAILED'", 'rm -f "${outfile}"')

    def _failed_envs(self, output: str) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".out", delete=False) as f:
            f.write(output)
        try:
            # The block uses `local`, as it does inside run_suite().
            script = ('set -euo pipefail; error(){ :; }; FAILED_ENVS=(); check(){ local env=dev outfile="%s"\n%s\n}; '
                      'check; echo "failed:${FAILED_ENVS[*]:-}"' % (f.name, self.BLOCK))
            res = _bash(script)
            self.assertEqual(res.returncode, 0, res.stderr)
            return res.stdout.strip()
        finally:
            os.unlink(f.name)

    def test_failed_assertions_mark_the_environment_failed(self):
        self.assertEqual(self._failed_envs("ok 1\nFAIL  test_x\n2 TEST(S) FAILED\n"), "failed:dev")

    def test_a_clean_run_is_not_marked_failed(self):
        self.assertEqual(self._failed_envs("142 passed\nALL TESTS PASSED\n"), "failed:")


# ── #182 ─────────────────────────────────────────────────────────────────────

@pytest.mark.tooling
class OfflineBundleStopsOnDownloadFailure(unittest.TestCase):
    SCRIPT = (ROOT / "scripts/offline/build_bundle.sh").read_text(encoding="utf-8")
    BLOCK = _between(SCRIPT, "REAL=()", "( cd \"$OUT/debs\" && apt-ftparchive", include_end=False)

    def _run(self, apt_get_body: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as d:
            bin_dir, out = Path(d) / "bin", Path(d) / "out"
            (out / "debs").mkdir(parents=True)
            bin_dir.mkdir()
            (bin_dir / "apt-cache").write_text("#!/bin/bash\necho 'Candidate: 1.0'\n")
            (bin_dir / "apt-get").write_text("#!/bin/bash\n" + apt_get_body)
            for f in bin_dir.iterdir():
                f.chmod(0o755)
            script = (f'set -euo pipefail; DEPS="pkg-a pkg-b"; PKGS="pkg-a pkg-b"; OUT="{out}"\n{self.BLOCK}\necho BUILT')
            return _bash(script, PATH=f"{bin_dir}:{os.environ['PATH']}")

    def test_the_old_swallow_is_gone(self):
        self.assertNotRegex(self.SCRIPT, r"apt-get download[^\n]*\|\|\s*true")

    def test_a_failed_download_stops_the_build(self):
        res = self._run("exit 1\n")
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn("BUILT", res.stdout)

    def test_a_download_that_yields_no_packages_stops_the_build(self):
        res = self._run("exit 0\n")  # claims success but fetched nothing
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("missing deb", res.stderr)

    def test_a_complete_download_continues(self):
        res = self._run('for p in "$@"; do [ "$p" = download ] || touch "${p}_1.0_amd64.deb"; done\n')
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("BUILT", res.stdout)


# ── #130 ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class FrontendLockFileMatchesPackageJson(unittest.TestCase):
    """#130: `npm ci` refuses a lock file that disagrees with package.json."""

    def test_root_entry_and_every_direct_dependency_agree(self):
        pkg = json.loads((ROOT / "csv-table-hub-main/package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "csv-table-hub-main/package-lock.json").read_text(encoding="utf-8"))
        root = lock["packages"][""]
        for section in ("dependencies", "devDependencies"):
            with self.subTest(section=section):
                self.assertEqual(root.get(section, {}), pkg.get(section, {}))
        for name in {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}:
            with self.subTest(package=name):
                self.assertIn(f"node_modules/{name}", lock["packages"])


# ── #169 ─────────────────────────────────────────────────────────────────────

@pytest.mark.tooling
class TestCatalogueIsCurrent(unittest.TestCase):
    def test_docs_test_cases_matches_the_tests(self):
        res = subprocess.run([sys.executable, "scripts/test_catalogue.py", "--check"], cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, "run `python3 scripts/test_catalogue.py` and commit:\n" + res.stdout[-800:])


# ── #194 ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class CoverageFloorGate(unittest.TestCase):
    FILES = ("api/services/csv_parse.py", "api/services/dynamic_loader.py", "api/services/te_loader.py")

    def _gate(self, pct: dict[str, float], drop: str | None = None) -> int:
        report = {"files": {f: {"summary": {"percent_covered": pct[f]}} for f in self.FILES if f != drop}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(report, f)
        try:
            # The gate prints box-drawing characters; a Windows console's default encoding can't.
            return subprocess.run([sys.executable, "scripts/check_coverage_floors.py", f.name], cwd=ROOT,
                                  capture_output=True, text=True, timeout=30,
                                  env={**os.environ, "PYTHONIOENCODING": "utf-8"}).returncode
        finally:
            os.unlink(f.name)

    def test_floors_cover_the_three_loaders(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import check_coverage_floors as gate
        finally:
            sys.path.pop(0)
        self.assertEqual(set(gate.FLOORS), set(self.FILES))

    def test_passes_at_100_percent(self):
        self.assertEqual(self._gate({f: 100.0 for f in self.FILES}), 0)

    def test_fails_when_one_loader_drops_below_its_floor(self):
        self.assertEqual(self._gate({**{f: 100.0 for f in self.FILES}, "api/services/te_loader.py": 10.0}), 1)

    def test_fails_when_a_loader_is_missing_from_the_report(self):
        self.assertEqual(self._gate({f: 100.0 for f in self.FILES}, drop="api/services/dynamic_loader.py"), 1)


# ── #207 ─────────────────────────────────────────────────────────────────────

@pytest.mark.unit
class ApiDocDefersToTheGeneratedSchema(unittest.TestCase):
    DOC = (ROOT / "docs/API_INTEGRATION.md").read_text(encoding="utf-8")

    def test_no_hand_kept_route_table(self):
        self.assertIsNone(re.search(r"^\|\s*`?(GET|POST|PUT|DELETE)\b", self.DOC, re.M),
                          "a hand-kept route table drifts from the code (#207)")

    def test_points_at_the_real_schema_urls_not_the_old_404(self):
        self.assertIn("/docs", self.DOC)
        self.assertIn("/openapi.json", self.DOC)
        self.assertNotIn("/api/docs", self.DOC)

    def test_the_documented_urls_are_served_without_a_key(self):
        from fastapi.testclient import TestClient
        from api.main import app
        client = TestClient(app)
        self.assertEqual(client.get("/docs").status_code, 200)
        paths = client.get("/openapi.json").json()["paths"]
        self.assertIn("/api/csv/upload", paths)
        self.assertIn("/api/csv/uploads/{upload_id}/rows", paths)

    def test_the_routers_it_names_exist(self):
        for name in ("auth", "csv", "review", "te", "audit"):
            with self.subTest(router=name):
                self.assertTrue((ROOT / "api/routers" / f"{name}_routes.py").exists())
