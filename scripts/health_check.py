#!/usr/bin/env python3
"""Health dashboard for PostgreDataMigrationApp.

Mirrors the role of `bun run skill:check` in gstack: walks every
expected project component and reports PASS / WARN / FAIL so CI or a
developer gets an instant picture of project health without running any
tests.

Exit code 0 when all checks pass; 1 if any check fails.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
CYAN   = "\033[0;36m"
NC     = "\033[0m"

_results: list[tuple[str, str, str]] = []  # (status, label, detail)


def _pass(label: str, detail: str = "") -> None:
    _results.append(("PASS", label, detail))


def _warn(label: str, detail: str) -> None:
    _results.append(("WARN", label, detail))


def _fail(label: str, detail: str) -> None:
    _results.append(("FAIL", label, detail))


def _check_file(label: str, path: Path) -> bool:
    if path.exists():
        _pass(label)
        return True
    _fail(label, f"missing: {path.relative_to(ROOT)}")
    return False


def _check_py_syntax(label: str, path: Path) -> None:
    if not path.exists():
        _fail(label, f"file missing: {path.relative_to(ROOT)}")
        return
    try:
        ast.parse(path.read_text(encoding="utf-8"))
        _pass(label)
    except SyntaxError as exc:
        _fail(label, f"syntax error at line {exc.lineno}: {exc.msg}")


# ── Core Python source ────────────────────────────────────────────────────────

def check_core_python() -> None:
    files = {
        "validator.py syntax":  ROOT / "build" / "csv" / "validator.py",
        "runner.py syntax":     ROOT / "evals" / "runner.py",
        "gap_report.py syntax": ROOT / "evals" / "gap_report.py",
    }
    for label, path in files.items():
        _check_py_syntax(label, path)


# ── Shell scripts ─────────────────────────────────────────────────────────────

def check_shell_scripts() -> None:
    scripts = [
        ROOT / "build" / "deploy_all.sh",
        ROOT / "build" / "setup.sh",
        ROOT / "build" / "csv_loader.sh",
        ROOT / "preflight.sh",
    ]
    adapters = (ROOT / "build" / "adapters").glob("adapter_*.sh")
    loaders  = (ROOT / "build" / "csv").glob("loader_*.sh")
    for path in [*scripts, *adapters, *loaders]:
        rel = path.relative_to(ROOT)
        _check_file(str(rel), path)


# ── SQL schema & environment files ───────────────────────────────────────────

def check_sql_files() -> None:
    pg_schema = ROOT / "build" / "schema" / "postgresql" / "te_core_schema.sql"
    _check_file("postgresql schema", pg_schema)

    # Concrete env_<env>.sql files are gitignored (they carry credentials);
    # only the committed template must exist. Concrete files are reported
    # informationally when present so local setups still get visibility.
    template = ROOT / "build" / "environments" / "env_dev.example.sql"
    _check_file("env template (env_dev.example.sql)", template)
    for env in ["dev", "test", "staging", "prod"]:
        path = ROOT / "build" / "environments" / f"env_{env}.sql"
        if path.exists():
            _pass(f"env_{env}.sql (local, gitignored)")

    suite_dir = ROOT / "tests" / "suites"
    suites = sorted(suite_dir.glob("test_*.sql")) if suite_dir.exists() else []
    if suites:
        for s in suites:
            _pass(f"test suite: {s.name}")
    else:
        _fail("SQL test suites", f"no test_*.sql files found in {suite_dir.relative_to(ROOT)}")

    framework = ROOT / "tests" / "framework" / "test_framework.sql"
    _check_file("test_framework.sql", framework)


# ── Eval datasets & expected files ────────────────────────────────────────────

def check_eval_coverage() -> None:
    datasets_root = ROOT / "evals" / "datasets"
    expected_root = ROOT / "evals" / "expected"

    if not datasets_root.exists():
        _fail("eval datasets dir", f"missing: {datasets_root.relative_to(ROOT)}")
        return

    for tier_dir in sorted(datasets_root.iterdir()):
        if not tier_dir.is_dir():
            continue
        tier = tier_dir.name  # e.g. "tier_p"
        short = tier.replace("tier_", "")
        scenarios = sorted(p for p in tier_dir.iterdir() if p.is_dir())
        if not scenarios:
            _warn(f"{tier}: scenarios", "no scenario directories found")
            continue
        for scenario in scenarios:
            exp_file = expected_root / tier / f"{scenario.name}.json"
            if exp_file.exists():
                _pass(f"{tier}/{scenario.name}: expected file")
            else:
                _fail(
                    f"{tier}/{scenario.name}: expected file",
                    f"missing: {exp_file.relative_to(ROOT)}",
                )
            if short == "p":
                inp = scenario / "input.csv"
                if inp.exists():
                    _pass(f"{tier}/{scenario.name}: input.csv")
                else:
                    exp_action = ""
                    if exp_file.exists():
                        import json
                        try:
                            d = json.loads(exp_file.read_text(encoding="utf-8"))
                            exp_action = d.get("runner_action", "default")
                        except Exception:
                            pass
                    if exp_action in ("", "default"):
                        _fail(f"{tier}/{scenario.name}: input.csv", "missing")
                    else:
                        _pass(f"{tier}/{scenario.name}: input.csv (generated by runner_action={exp_action})")


# ── Test infrastructure ───────────────────────────────────────────────────────

def check_test_infra() -> None:
    files = {
        "pytest.ini":        ROOT / "pytest.ini",
        "conftest.py":       ROOT / "tests" / "conftest.py",
        "requirements-dev":  ROOT / "requirements-dev.txt",
        "Makefile":          ROOT / "Makefile",
        "run_qa.ps1":        ROOT / "scripts" / "run_qa.ps1",
    }
    for label, path in files.items():
        _check_file(label, path)

    test_files = list((ROOT / "tests").glob("test_*.py"))
    if test_files:
        _pass(f"python test files ({len(test_files)} found)")
    else:
        _fail("python test files", "no test_*.py found in tests/")


# ── Config template ───────────────────────────────────────────────────────────

def check_config() -> None:
    example = ROOT / "build" / "config.env.example"
    if not example.exists():
        _fail("config.env.example", "missing")
        return
    content = example.read_text(encoding="utf-8")
    if 'PG_PASSWORD=""' in content or "PG_PASSWORD=''" in content:
        _pass("config.env.example: PG_PASSWORD is empty (safe default)")
    else:
        _warn("config.env.example: PG_PASSWORD", "value may not be empty — check for accidental credential commit")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    print(f"\n{CYAN}PostgreDataMigrationApp — Health Dashboard{NC}")
    print("=" * 60)

    check_core_python()
    check_shell_scripts()
    check_sql_files()
    check_eval_coverage()
    check_test_infra()
    check_config()

    print()
    passes = warns = fails = 0
    for status, label, detail in _results:
        if status == "PASS":
            passes += 1
            print(f"  {GREEN}PASS{NC}  {label}")
        elif status == "WARN":
            warns += 1
            print(f"  {YELLOW}WARN{NC}  {label}: {detail}")
        else:
            fails += 1
            print(f"  {RED}FAIL{NC}  {label}: {detail}")

    print()
    print("=" * 60)
    print(f"  {GREEN}{passes} passed{NC}  {YELLOW}{warns} warnings{NC}  {RED}{fails} failed{NC}")
    print()

    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
