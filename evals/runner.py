#!/usr/bin/env python3
"""evals/runner.py — eval runner for PostgreDataMigrationApp.

Tier P (Python CSV validator) is fully implemented and runs offline.
Tier I (idempotency) and Tier S (SQL suite) require a reachable PostgreSQL
via psql; they SKIP cleanly when unavailable.

Usage
-----
    python3 evals/runner.py                  # Tier P only (default)
    python3 evals/runner.py --tiers p,i,s    # all three tiers
    python3 evals/runner.py --only 05_mixed_valid_skipped
    python3 evals/runner.py --verbose
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Locations

EVALS_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT = EVALS_DIR.parent
VALIDATOR    = PROJECT_ROOT / "build" / "csv" / "validator.py"

DATASETS_DIR = EVALS_DIR / "datasets"
EXPECTED_DIR = EVALS_DIR / "expected"
REPORTS_DIR  = EVALS_DIR / "reports"


# ---------------------------------------------------------------------------
# Pretty-printing

GREEN  = "\033[0;32m"
YELLOW = "\033[1;33m"
RED    = "\033[0;31m"
BLUE   = "\033[0;34m"
DIM    = "\033[2m"
NC     = "\033[0m"


def _pass(name: str) -> str: return GREEN + "PASS" + NC + " " + name
def _fail(name: str) -> str: return RED   + "FAIL" + NC + " " + name
def _skip(name: str) -> str: return YELLOW + "SKIP" + NC + " " + name
def _info(name: str) -> str: return BLUE  + "INFO" + NC + " " + name


# ---------------------------------------------------------------------------
# Data classes

class ScenarioResult:
    """Outcome of running a single scenario."""

    def __init__(self, tier: str, name: str) -> None:
        self.tier      = tier
        self.name      = name
        self.passed    = False
        self.skipped   = False
        self.errors:   List[str] = []
        self.actual:   Dict[str, Any] = {}
        self.expected: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier":    self.tier,
            "name":    self.name,
            "passed":  self.passed,
            "skipped": self.skipped,
            "errors":  self.errors,
            "actual":  self.actual,
            "expected": self.expected,
        }


# ---------------------------------------------------------------------------
# Helpers

def _load_expected(tier: str, name: str) -> Optional[Dict[str, Any]]:
    path = EXPECTED_DIR / ("tier_" + tier) / (name + ".json")
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _read_csv_rows(path: Path) -> List[List[str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return [[cell.replace("\r\n", "\n") for cell in row] for row in csv.reader(f)]


# ---------------------------------------------------------------------------
# Tier P — Python CSV validator

def _run_validator(env: Dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def run_tier_p_scenario(scenario_dir: Path) -> ScenarioResult:
    name   = scenario_dir.name
    result = ScenarioResult(tier="p", name=name)

    expected = _load_expected("p", name)
    if expected is None:
        result.errors.append("No expected file at expected/tier_p/" + name + ".json")
        return result
    result.expected = expected

    runner_action = expected.get("runner_action", "default")
    exp           = expected.get("expected", {})

    with tempfile.TemporaryDirectory(prefix="eval_" + name + "_") as tmp:
        tmp_path  = Path(tmp)
        valid_csv = tmp_path / "valid.csv"
        skip_csv  = tmp_path / "skip.csv"

        env = {
            "PATH":             os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
        }

        if runner_action == "default":
            src_csv = scenario_dir / "input.csv"
            if not src_csv.exists():
                result.errors.append("Missing input.csv at " + str(src_csv))
                return result
            csv_file = tmp_path / "input.csv"
            shutil.copyfile(src_csv, csv_file)
            env["CSV_FILE"]   = str(csv_file)
            env["VALID_CSV"]  = str(valid_csv)
            env["SKIP_FILE"]  = str(skip_csv)
            env["TABLE_NAME"] = expected.get("table_name", "people")

        elif runner_action == "write_long_field_file":
            csv_file = tmp_path / "input.csv"
            long_value = "x" * int(expected.get("field_size_bytes", 50_000))
            with csv_file.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["id", "payload"])
                writer.writerow(["1", long_value])
            env["CSV_FILE"]   = str(csv_file)
            env["VALID_CSV"]  = str(valid_csv)
            env["SKIP_FILE"]  = str(skip_csv)
            env["TABLE_NAME"] = expected.get("table_name", "payloads")

        elif runner_action == "write_invalid_utf8_file":
            csv_file = tmp_path / "input.csv"
            csv_file.write_bytes(b"id,name\n1,Alice\n2,\xe9\n")
            env["CSV_FILE"]   = str(csv_file)
            env["VALID_CSV"]  = str(valid_csv)
            env["SKIP_FILE"]  = str(skip_csv)
            env["TABLE_NAME"] = expected.get("table_name", "people")

        elif runner_action == "omit_env_vars":
            pass

        elif runner_action == "point_at_missing_file":
            env["CSV_FILE"]   = str(tmp_path / "does_not_exist.csv")
            env["VALID_CSV"]  = str(valid_csv)
            env["SKIP_FILE"]  = str(skip_csv)
            env["TABLE_NAME"] = "people"

        else:
            result.errors.append("Unknown runner_action: " + repr(runner_action))
            return result

        try:
            cp = _run_validator(env)
        except FileNotFoundError as e:
            result.errors.append("Cannot launch validator: " + str(e))
            return result

        actual: Dict[str, Any] = {
            "exit_code": cp.returncode,
            "stdout":    cp.stdout,
            "stderr":    cp.stderr,
        }

        reads_output_files = runner_action in {
            "default",
            "write_long_field_file",
            "write_invalid_utf8_file",
        }

        if reads_output_files:
            actual["valid_csv_rows"]     = _read_csv_rows(valid_csv)
            skip_rows                    = _read_csv_rows(skip_csv)
            actual["skip_csv_rows"]      = skip_rows
            actual["skip_csv_row_count"] = max(0, len(skip_rows) - 1)
        else:
            actual["valid_csv_rows"]     = None
            actual["skip_csv_rows"]      = None
            actual["skip_csv_row_count"] = None

        result.actual = actual

        errors: List[str] = []

        if "exit_code" in exp and exp["exit_code"] != actual["exit_code"]:
            errors.append(
                "exit_code: expected "
                + str(exp["exit_code"])
                + ", got "
                + str(actual["exit_code"])
            )

        for needle in exp.get("stdout_contains", []) or []:
            if needle not in actual["stdout"]:
                errors.append("stdout missing substring: " + repr(needle))

        for needle in exp.get("stderr_contains", []) or []:
            if needle not in actual["stderr"]:
                errors.append("stderr missing substring: " + repr(needle))

        exp_valid_rows = exp.get("valid_csv_rows")
        if exp_valid_rows is not None:
            if actual["valid_csv_rows"] != exp_valid_rows:
                errors.append(
                    "valid_csv_rows mismatch:\n"
                    "  expected: " + str(exp_valid_rows) + "\n"
                    "  actual:   " + str(actual["valid_csv_rows"])
                )

        exp_skip_count = exp.get("skip_csv_row_count")
        if exp_skip_count is not None:
            if actual["skip_csv_row_count"] != exp_skip_count:
                errors.append(
                    "skip_csv_row_count: expected "
                    + str(exp_skip_count)
                    + ", got "
                    + str(actual["skip_csv_row_count"])
                )

        for needle in exp.get("skip_reasons_contain", []) or []:
            reasons = []
            if actual["skip_csv_rows"]:
                for row in actual["skip_csv_rows"][1:]:
                    if row:
                        reasons.append(row[-1])
            if not any(needle in r for r in reasons):
                errors.append(
                    "skip_reasons missing substring: " + repr(needle)
                    + "; actual reasons: " + str(reasons)
                )

        result.errors = errors
        result.passed = not errors

    return result


# ---------------------------------------------------------------------------
# PostgreSQL connectivity helpers (shared by Tier I + Tier S)

def _have_psql() -> bool:
    return shutil.which("psql") is not None


def _pg_env() -> Dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PGUSER", "postgres")
    return env


def _can_connect_pg() -> bool:
    if not _have_psql():
        return False
    try:
        r = subprocess.run(
            ["psql", "-tA", "-c", "SELECT 1"],
            env=_pg_env(),
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


_DEV_SEED_TABLES = [
    "organisations", "personnel", "test_programs", "temp_documents",
    "test_phases", "requirements", "test_cases", "vcrm_entries",
    "test_events", "test_results", "defect_reports",
]


def _count_dev_rows() -> Dict[str, Any]:
    counts: Dict[str, Any] = {}
    for tbl in _DEV_SEED_TABLES:
        # tbl comes from the hardcoded _DEV_SEED_TABLES constant — not injectable
        query = 'SELECT count(*) FROM te_dev."' + tbl + '";'  # nosec B608
        r = subprocess.run(
            ["psql", "-tA", "-d", "te_mgmt_dev", "-c", query],
            env=_pg_env(),
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip().isdigit():
            counts[tbl] = int(r.stdout.strip())
        else:
            counts[tbl] = None
    return counts


# ---------------------------------------------------------------------------
# Tier I — Idempotency

def run_tier_i_scenario(scenario_dir: Path) -> ScenarioResult:
    name   = scenario_dir.name
    result = ScenarioResult(tier="i", name=name)

    expected = _load_expected("i", name)
    if expected is None:
        result.errors.append("No expected file at expected/tier_i/" + name + ".json")
        return result
    result.expected = expected

    if not _can_connect_pg():
        # An unavailable prerequisite is a FAILURE, not a skip: a green run
        # must mean the scenario actually executed.
        result.errors.append(
            "PostgreSQL not reachable via psql "
            "(install psql + start PG, or set PG* env vars)."
        )
        return result

    if name == "01_deploy_dev_twice":
        return _run_deploy_dev_twice(result, expected)

    result.errors.append("Unknown tier-I scenario: " + name)
    return result


def _run_deploy_dev_twice(
    result: ScenarioResult, expected: Dict[str, Any]
) -> ScenarioResult:
    env_dev_sql = PROJECT_ROOT / "build" / "environments" / "env_dev.sql"
    if not env_dev_sql.exists():
        result.errors.append("Cannot find " + str(env_dev_sql))
        return result

    env = _pg_env()
    psql_args = ["psql", "-f", str(env_dev_sql)]

    r1 = subprocess.run(psql_args, env=env, capture_output=True, text=True, timeout=120)
    counts_1 = _count_dev_rows()

    r2 = subprocess.run(psql_args, env=env, capture_output=True, text=True, timeout=120)
    counts_2 = _count_dev_rows()

    actual = {
        "first_run_exit_code":  r1.returncode,
        "second_run_exit_code": r2.returncode,
        "row_counts_first":     counts_1,
        "row_counts_second":    counts_2,
        "row_counts_unchanged": counts_1 == counts_2,
        "tables_present":       sum(1 for v in counts_2.values() if v is not None),
    }
    result.actual = actual

    exp = expected.get("expected", {})
    errors: List[str] = []

    if exp.get("first_run_exit_code") != actual["first_run_exit_code"]:
        r1_tail = r1.stderr[-400:]
        errors.append(
            "first_run_exit_code: expected " + str(exp.get("first_run_exit_code"))
            + ", got " + str(actual["first_run_exit_code"])
            + "; stderr: " + r1_tail
        )
    if exp.get("second_run_exit_code") != actual["second_run_exit_code"]:
        r2_tail = r2.stderr[-400:]
        errors.append(
            "second_run_exit_code: expected " + str(exp.get("second_run_exit_code"))
            + ", got " + str(actual["second_run_exit_code"])
            + "; stderr: " + r2_tail
        )
    if exp.get("row_counts_unchanged") and not actual["row_counts_unchanged"]:
        drift = {
            t: (counts_1.get(t), counts_2.get(t))
            for t in counts_1
            if counts_1.get(t) != counts_2.get(t)
        }
        errors.append("row counts changed between runs: " + str(drift))
    min_tables = exp.get("min_seeded_tables_present", 0)
    if actual["tables_present"] < min_tables:
        errors.append(
            "tables_present: expected >= " + str(min_tables)
            + ", got " + str(actual["tables_present"])
        )

    result.errors = errors
    result.passed = not errors
    return result


# ---------------------------------------------------------------------------
# Tier S — SQL suite integration

def run_tier_s_scenario(scenario_dir: Path) -> ScenarioResult:
    name   = scenario_dir.name
    result = ScenarioResult(tier="s", name=name)

    expected = _load_expected("s", name)
    if expected is None:
        result.errors.append("No expected file at expected/tier_s/" + name + ".json")
        return result
    result.expected = expected

    if not _can_connect_pg():
        # Unavailable prerequisite = failure, not skip (see tier_i note above).
        result.errors.append(
            "PostgreSQL not reachable via psql — install/start PG and re-run."
        )
        return result

    if name == "01_fresh_deploy_then_all_tests_pass":
        return _run_fresh_deploy_then_tests(result, expected)

    result.errors.append("Unknown tier-S scenario: " + name)
    return result


def _run_fresh_deploy_then_tests(
    result: ScenarioResult, expected: Dict[str, Any]
) -> ScenarioResult:
    env_dev_sql = PROJECT_ROOT / "build" / "environments" / "env_dev.sql"
    run_tests   = PROJECT_ROOT / "tests" / "run_all_tests.sql"
    if not env_dev_sql.exists() or not run_tests.exists():
        result.errors.append(
            "Cannot find " + str(env_dev_sql) + " or " + str(run_tests)
        )
        return result

    env = _pg_env()

    deploy = subprocess.run(
        ["psql", "-f", str(env_dev_sql)],
        env=env, capture_output=True, text=True, timeout=180,
    )

    table_overrides = [
        "--set", "schema_name=te_dev",
        "--set", "app_user=te_dev_user",
        "--set", "conn_limit=10",
        "--set", "tbl_organisations=organisations",
        "--set", "tbl_personnel=personnel",
        "--set", "tbl_test_programs=test_programs",
        "--set", "tbl_temp_documents=temp_documents",
        "--set", "tbl_test_phases=test_phases",
        "--set", "tbl_requirements=requirements",
        "--set", "tbl_test_cases=test_cases",
        "--set", "tbl_vcrm_entries=vcrm_entries",
        "--set", "tbl_test_events=test_events",
        "--set", "tbl_test_results=test_results",
        "--set", "tbl_defect_reports=defect_reports",
        "--set", "tbl_evidence_artifacts=evidence_artifacts",
    ]
    tests = subprocess.run(
        ["psql", "-d", "te_mgmt_dev"] + table_overrides + ["-f", str(run_tests)],
        env=env, capture_output=True, text=True, timeout=180,
    )

    stdout_tail = tests.stdout[-2000:]
    stderr_tail = tests.stderr[-400:]
    actual: Dict[str, Any] = {
        "deploy_exit_code": deploy.returncode,
        "tests_exit_code":  tests.returncode,
        "stdout_tail":      stdout_tail,
        "stderr_tail":      stderr_tail,
    }

    total_assertions = None
    pass_rate        = None
    for line in tests.stdout.splitlines():
        # Summary row may be plain ("142 142 0 100.0% ...") or a psql table
        # row ("142 |  142 |  0 | 0 | 100.0% | ..."); strip pipes first.
        parts = line.replace("|", " ").split()
        if (len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit()
                and parts[2].isdigit()):
            pct = next((p for p in parts[3:] if p.endswith("%")), None)
            if pct is not None:
                try:
                    total_assertions = int(parts[0])
                    pass_rate        = float(pct.rstrip("%"))
                except ValueError:
                    pass
    actual["total_assertions"] = total_assertions
    actual["pass_rate"]        = pass_rate
    result.actual              = actual

    exp = expected.get("expected", {})
    errors: List[str] = []
    if exp.get("deploy_exit_code") != deploy.returncode:
        deploy_tail = deploy.stderr[-400:]
        errors.append(
            "deploy_exit_code: expected " + str(exp.get("deploy_exit_code"))
            + ", got " + str(deploy.returncode)
            + "; stderr: " + deploy_tail
        )
    if exp.get("tests_exit_code") != tests.returncode:
        errors.append(
            "tests_exit_code: expected " + str(exp.get("tests_exit_code"))
            + ", got " + str(tests.returncode)
        )
    for needle in exp.get("stdout_contains", []) or []:
        if needle not in tests.stdout:
            errors.append("stdout missing substring: " + repr(needle))
    min_total = exp.get("min_total_assertions", 0)
    if total_assertions is None or total_assertions < min_total:
        errors.append(
            "total_assertions: expected >= " + str(min_total)
            + ", got " + str(total_assertions)
        )
    min_rate = exp.get("min_pass_rate_percent", 0.0)
    if pass_rate is None or pass_rate < min_rate:
        errors.append(
            "pass_rate: expected >= " + str(min_rate)
            + "%, got " + str(pass_rate)
        )

    result.errors = errors
    result.passed = not errors
    return result


# ---------------------------------------------------------------------------
# Tier E — Cross-environment structural parity (VCRM BR-01)
#
# BR-01 claims Dev/Test/Staging/Prod are deployed from one parameterised schema
# and differ only in their identifier namespace. Nothing asserted that. An edit
# to env_staging.sql that added a column, or dropped a constraint, would deploy
# cleanly and no test would notice until production data met a schema nobody had
# compared. This tier compares the four deployed schemas column by column.
#
# Only the identifier namespace (database + schema name) may differ. Everything
# structural — table set, column names, declared types, nullability, ordinal
# position — must be identical.

ENV_TARGETS = [
    ("dev",     "te_mgmt_dev",     "te_dev"),
    ("test",    "te_mgmt_test",    "te_test"),
    ("staging", "te_mgmt_staging", "te_staging"),
    ("prod",    "te_mgmt_prod",    "te_prod"),
]


def _deploy_env(env_name: str) -> Dict[str, Any]:
    """Deploy one environment from its committed launcher. Returns exit info.

    env_<env>.sql is gitignored and materialised from env_<env>.example.sql (see
    FIXES_APPLIED.md F3), so accept either and say which was used.
    """
    env_dir = PROJECT_ROOT / "build" / "environments"
    launcher = env_dir / ("env_" + env_name + ".sql")
    if not launcher.exists():
        launcher = env_dir / ("env_" + env_name + ".example.sql")
    if not launcher.exists():
        return {"env": env_name, "exit_code": None,
                "error": "No env_" + env_name + ".sql or .example.sql found"}
    r = subprocess.run(
        ["psql", "-v", "ON_ERROR_STOP=1", "-f", str(launcher)],
        env=_pg_env(), capture_output=True, text=True, timeout=180,
    )
    return {
        "env": env_name,
        "launcher": launcher.name,
        "exit_code": r.returncode,
        "stderr_tail": r.stderr[-300:],
    }


def _column_signature(db: str, schema: str) -> Dict[str, List[str]]:
    """Structural fingerprint of one deployed schema.

    Maps table name -> ordered list of "column:type:nullability" strings. The
    schema name is deliberately absent from the value so two environments with
    different namespaces compare equal when their structure matches.
    """
    # The schema name is bound by psql via --set + :'sch' rather than pasted into
    # the SQL text, so there is no string interpolation to reason about even
    # though the value comes from the ENV_TARGETS constant.
    query = (
        "SELECT table_name, column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        "WHERE table_schema = :'sch' "
        "ORDER BY table_name, ordinal_position"
    )
    r = subprocess.run(
        ["psql", "-tA", "-d", db, "--set=sch=" + schema, "-c", query],
        env=_pg_env(), capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return {}
    sig: Dict[str, List[str]] = {}
    for line in r.stdout.splitlines():
        parts = line.split("|")
        if len(parts) != 4:
            continue
        table, column, dtype, nullable = (p.strip() for p in parts)
        sig.setdefault(table, []).append(column + ":" + dtype + ":" + nullable)
    return sig


def _diff_signatures(ref_env: str, ref: Dict[str, List[str]],
                     other_env: str, other: Dict[str, List[str]]) -> List[str]:
    """Human-readable differences between two schema fingerprints."""
    diffs: List[str] = []
    missing = sorted(set(ref) - set(other))
    extra   = sorted(set(other) - set(ref))
    if missing:
        diffs.append(other_env + " is missing tables present in " + ref_env
                     + ": " + ", ".join(missing))
    if extra:
        diffs.append(other_env + " has tables absent from " + ref_env
                     + ": " + ", ".join(extra))
    for table in sorted(set(ref) & set(other)):
        if ref[table] != other[table]:
            ref_cols   = set(ref[table])
            other_cols = set(other[table])
            only_ref   = sorted(ref_cols - other_cols)
            only_other = sorted(other_cols - ref_cols)
            if only_ref or only_other:
                diffs.append(
                    "table " + table + " differs: " + ref_env + "-only ["
                    + ", ".join(only_ref) + "], " + other_env + "-only ["
                    + ", ".join(only_other) + "]"
                )
            else:
                # Same columns, different order — still drift worth failing on,
                # because ordinal position is part of the deployed contract.
                diffs.append("table " + table + " has the same columns in a "
                             "different ordinal order between " + ref_env
                             + " and " + other_env)
    return diffs


def run_tier_e_scenario(scenario_dir: Path) -> ScenarioResult:
    name   = scenario_dir.name
    result = ScenarioResult(tier="e", name=name)

    expected = _load_expected("e", name)
    if expected is None:
        result.errors.append("No expected file at expected/tier_e/" + name + ".json")
        return result
    result.expected = expected

    if not _can_connect_pg():
        # Same no-skip stance as Tiers I and S (FIXES_APPLIED.md F5): a missing
        # prerequisite fails, so a green run always means the check really ran.
        result.errors.append(
            "PostgreSQL not reachable via psql "
            "(install psql + start PG, or set PG* env vars)."
        )
        return result

    if name == "01_envs_have_identical_structure":
        return _run_envs_have_identical_structure(result, expected)

    result.errors.append("Unknown tier-E scenario: " + name)
    return result


def _run_envs_have_identical_structure(
    result: ScenarioResult, expected: Dict[str, Any]
) -> ScenarioResult:
    exp = expected.get("expected", {})
    envs_under_test = expected.get("envs_under_test",
                                   [e[0] for e in ENV_TARGETS])
    targets = [t for t in ENV_TARGETS if t[0] in envs_under_test]

    deploys = [_deploy_env(env_name) for env_name, _, _ in targets]
    signatures: Dict[str, Dict[str, List[str]]] = {}
    for env_name, db, schema in targets:
        signatures[env_name] = _column_signature(db, schema)

    table_counts = {e: len(sig) for e, sig in signatures.items()}
    result.actual = {
        "deploys": deploys,
        "table_counts": table_counts,
    }

    errors: List[str] = []

    if exp.get("all_envs_deploy_exit_zero") is True:
        for d in deploys:
            if d.get("exit_code") != 0:
                errors.append(
                    "deploy of " + d["env"] + " exited "
                    + str(d.get("exit_code")) + " "
                    + (d.get("error") or d.get("stderr_tail") or "")
                )

    min_tables = int(exp.get("min_tables_per_env", 12))
    for env_name, count in sorted(table_counts.items()):
        if count < min_tables:
            errors.append(
                "env " + env_name + " has " + str(count) + " tables in its "
                "schema, expected >= " + str(min_tables)
                + " (deploy may have partially failed)"
            )

    if exp.get("column_signature_identical_across_envs") is True:
        # dev is the reference: it is the environment every other test exercises,
        # so drift is defined as "differs from what the suite actually validates".
        ref_env = expected.get("reference_env", "dev")
        ref = signatures.get(ref_env)
        if not ref:
            errors.append("reference env " + ref_env + " returned no columns; "
                          "cannot compare the others against it")
        else:
            for env_name in sorted(signatures):
                if env_name == ref_env:
                    continue
                diffs = _diff_signatures(ref_env, ref, env_name,
                                         signatures[env_name])
                errors.extend(diffs)
            result.actual["signature_match"] = not errors

    result.errors = errors
    result.passed = not errors
    return result


# ---------------------------------------------------------------------------
# Tier X — Cross-engine structural coverage (VCRM BR-02)
#
# BR-02 claims six engines are supported through adapter scripts. Only
# PostgreSQL was ever executed; the other five rested on code review. This tier
# starts closing that with SQLite, the cheapest engine to verify because it needs
# no service.
#
# Deliberate scope: this executes the DDL in build/schema/sqlite/, not
# adapter_sqlite.sh. Two reasons. The DDL is the artifact that drifts — the
# adapter is a thin sed + sqlite3 wrapper around it. And using Python's stdlib
# sqlite3 module means no sqlite3 binary is required, so this scenario also runs
# on the Windows CI job, where GAP_ANALYSIS.md G2 blocks anything needing a
# database service. The adapter script itself remains unexercised; that is a
# smaller, separate gap and is recorded rather than glossed over.
#
# The comparison is table-set and column-name only. Declared types are
# deliberately NOT compared across engines: SQLite has no native UUID or
# TIMESTAMPTZ and stores both as TEXT, so a type diff would fire constantly
# while telling us nothing. Structural presence is the property BR-02 asserts.

_ENGINE_PLACEHOLDER_TABLES = [
    "organisations", "personnel", "test_programs", "temp_documents",
    "test_phases", "requirements", "test_cases", "vcrm_entries",
    "test_events", "test_results", "defect_reports", "evidence_artifacts",
]


def _substitute_placeholders(ddl: str) -> str:
    """Replace {{TBL_*}} tokens the way adapter_sqlite.sh's sed pass does.

    Uses the table's own name as its value, which is what every environment file
    does for the default deployment.
    """
    for tbl in _ENGINE_PLACEHOLDER_TABLES:
        ddl = ddl.replace("{{TBL_" + tbl.upper() + "}}", tbl)
    return ddl


def _sqlite_structure(ddl: str) -> Dict[str, Any]:
    """Execute DDL in an in-memory SQLite database and read back its structure.

    Returns {"tables": {name: [columns]}} or {"error": "..."} if the DDL is
    rejected — a syntax error in the SQLite schema is itself a finding.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(":memory:")
    except Exception as exc:  # noqa: BLE001
        return {"error": "cannot open in-memory SQLite: " + str(exc)}
    try:
        conn.executescript(ddl)
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        tables = [r[0] for r in cur.fetchall()]
        out: Dict[str, List[str]] = {}
        for t in tables:
            # Table names come from sqlite_master in this same database, so there
            # is no external input here.
            cur.execute('PRAGMA table_info("' + t.replace('"', '""') + '")')
            out[t] = sorted(r[1] for r in cur.fetchall())
        return {"tables": out}
    except Exception as exc:  # noqa: BLE001 — a rejected DDL is a real result
        return {"error": type(exc).__name__ + ": " + str(exc)}
    finally:
        conn.close()


def run_tier_x_scenario(scenario_dir: Path) -> ScenarioResult:
    name   = scenario_dir.name
    result = ScenarioResult(tier="x", name=name)

    expected = _load_expected("x", name)
    if expected is None:
        result.errors.append("No expected file at expected/tier_x/" + name + ".json")
        return result
    result.expected = expected

    if name == "01_sqlite_schema_structure":
        return _run_sqlite_schema_structure(result, expected)

    result.errors.append("Unknown tier-X scenario: " + name)
    return result


def _run_sqlite_schema_structure(
    result: ScenarioResult, expected: Dict[str, Any]
) -> ScenarioResult:
    exp = expected.get("expected", {})
    ddl_path = PROJECT_ROOT / "build" / "schema" / "sqlite" / "te_core_schema.sql"
    if not ddl_path.exists():
        result.errors.append("SQLite DDL not found at " + str(ddl_path))
        return result

    raw = ddl_path.read_text(encoding="utf-8")
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", _substitute_placeholders(raw))
    structure = _sqlite_structure(_substitute_placeholders(raw))

    if "error" in structure:
        result.actual = structure
        result.errors.append("SQLite rejected its own DDL: " + structure["error"])
        return result

    tables = structure["tables"]
    result.actual = {
        "table_count": len(tables),
        "tables_present": sorted(tables),
        "unsubstituted_placeholders": sorted(set(leftover)),
    }

    errors: List[str] = []

    # Any {{TBL_*}} the substitution missed would reach sqlite3 as a literal and
    # silently create a differently-named table.
    if leftover:
        errors.append("DDL still contains unsubstituted placeholders: "
                      + ", ".join(sorted(set(leftover))))

    # Baseline guard. expected_tables is the set SQLite actually ships today, so
    # this passes on the known state and fails the moment it drifts either way:
    # a table removed, or a new one added without updating this file.
    expected_tables = exp.get("expected_tables")
    if expected_tables is not None:
        want, have = set(expected_tables), set(tables)
        missing, extra = sorted(want - have), sorted(have - want)
        if missing:
            errors.append("expected tables absent from the SQLite DDL: "
                          + ", ".join(missing))
        if extra:
            errors.append(
                "SQLite DDL defines tables not in expected_tables: "
                + ", ".join(extra)
                + " — if this is intentional progress toward full parity, add "
                "them to expected_tables and update known_missing_tables"
            )

    # Column presence per table, where the expectation file pins it.
    for table, want_cols in (exp.get("expected_columns") or {}).items():
        have_cols = tables.get(table)
        if have_cols is None:
            continue  # already reported by the table-set check above
        absent = sorted(set(want_cols) - set(have_cols))
        if absent:
            errors.append("table " + table + " is missing columns: "
                          + ", ".join(absent))

    # The parity shortfall is recorded, not asserted — see NOTES.txt. Surfacing
    # it in actual output keeps it visible in every report without turning the
    # scenario red for work that is knowingly outstanding.
    known_missing = exp.get("known_missing_tables") or []
    if known_missing:
        result.actual["known_missing_tables"] = known_missing
        result.actual["parity_note"] = (
            "SQLite ships " + str(len(tables)) + " of "
            + str(len(_ENGINE_PLACEHOLDER_TABLES))
            + " T&E tables. Outstanding work tracked in docs/ENGINE_PARITY_TODO.md."
        )

    result.errors = errors
    result.passed = not errors
    return result


# ---------------------------------------------------------------------------
# Orchestration

TIER_RUNNERS = {
    "p": run_tier_p_scenario,
    "i": run_tier_i_scenario,
    "s": run_tier_s_scenario,
    "e": run_tier_e_scenario,
    "x": run_tier_x_scenario,
}


def discover_scenarios(tier: str, only):
    base = DATASETS_DIR / ("tier_" + tier)
    if not base.exists():
        return []
    folders = sorted(p for p in base.iterdir() if p.is_dir())
    if only:
        folders = [p for p in folders if p.name == only]
    return folders


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval runner for PostgreDataMigrationApp")
    parser.add_argument("--tiers", default="p")
    parser.add_argument("--only", default=None)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    tiers = [t.strip().lower() for t in args.tiers.split(",") if t.strip()]
    for t in tiers:
        if t not in TIER_RUNNERS:
            print(_fail("Unknown tier: " + t))
            return 2

    if not VALIDATOR.exists():
        print(_fail("build/csv/validator.py not found at " + str(VALIDATOR)))
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    run_dir = REPORTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    total = passed = failed = skipped = 0
    all_results: List[ScenarioResult] = []

    for t in tiers:
        scenarios = discover_scenarios(t, args.only)
        if not scenarios:
            if args.only:
                print(_info("No scenarios matched --only=" + args.only + " in tier " + t))
            else:
                print(_info("No scenarios in tier_" + t))
            continue

        print("\n" + BLUE + "=== Tier " + t.upper() + " - " + str(len(scenarios)) + " scenarios ===" + NC)
        for s in scenarios:
            total += 1
            result = TIER_RUNNERS[t](s)
            all_results.append(result)
            label = "tier_" + t + "/" + result.name
            if result.skipped:
                skipped += 1
                print(_skip(label) + "  " + DIM + "; ".join(result.errors) + NC)
            elif result.passed:
                passed += 1
                print(_pass(label))
            else:
                failed += 1
                print(_fail(label))
                for e in result.errors:
                    print("     " + DIM + e + NC)
                if args.verbose:
                    snippet = json.dumps(result.actual, ensure_ascii=False)[:500]
                    print("     actual: " + snippet)

    print("\n" + BLUE + "=== Summary ===" + NC)
    print("  total:   " + str(total))
    print("  passed:  " + GREEN + str(passed) + NC)
    print("  failed:  " + (RED if failed else NC) + str(failed) + NC)
    print("  skipped: " + (YELLOW if skipped else NC) + str(skipped) + NC)

    summary = {
        "run_id":     run_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "tiers":      tiers,
        "totals":     {"total": total, "passed": passed, "failed": failed, "skipped": skipped},
        "scenarios":  [r.to_dict() for r in all_results],
    }
    summary_path = run_dir / "summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("\n  report:  " + str(summary_path))

    # Per-run VCRM gap report (see gap_report.py for the BR catalogue).
    # Best-effort: never fail the run if the report can't be generated.
    try:
        sys.path.insert(0, str(EVALS_DIR))
        import gap_report
        gap_path = gap_report.generate_for_run(run_dir, summary_path)
        print("  gap report: " + str(gap_path))
    except Exception as exc:  # noqa: BLE001
        print("  gap report skipped: " + type(exc).__name__ + ": " + str(exc))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
