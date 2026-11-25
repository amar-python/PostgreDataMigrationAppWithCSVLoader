"""Auto-migrate: drop a CSV, get a PostgreSQL table.

Reads the CSV, infers column types from data, generates schema SQL,
creates the table, appends to config.yaml, and runs the migration.

Usage:
    python auto_migrate.py my_data.csv
    python auto_migrate.py my_data.csv --dry-run
    python auto_migrate.py C:\\full\\path\\to\\data.csv
"""
from __future__ import annotations

import argparse
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

import pandas as pd
import psycopg2
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path.home()
sys.path.insert(0, str(REPO_ROOT))

from src.config import load_db_config  # noqa: E402

INPUT_DIR = SCRIPT_DIR / "input_data"
CONFIG_PATH = REPO_ROOT / "config.yaml"


# ---------------------------------------------------------------------------
# Header detection
# ---------------------------------------------------------------------------

def _looks_like_header(row: list[str]) -> bool:
    """Return True if the first row looks like column names, not data."""
    if not row:
        return False
    num_data_like = 0
    for val in row:
        val = val.strip()
        # Pure numbers → data
        try:
            float(val)
            num_data_like += 1
            continue
        except ValueError:
            pass
        # Date patterns → data
        if re.match(r"^\d{4}-\d{2}-\d{2}", val) or re.match(r"^\d{2}/\d{2}/\d{4}", val):
            num_data_like += 1
            continue
        # Boolean literals → data
        if val.lower() in ("true", "false", "yes", "no"):
            num_data_like += 1
            continue
    # If more than half the values look like data, it's not a header row
    return num_data_like <= len(row) // 2


# ---------------------------------------------------------------------------
# Type inference
# ---------------------------------------------------------------------------

def _is_integer(series: pd.Series) -> bool:
    for v in series.dropna():
        try:
            f = float(v)
            if f != int(f):
                return False
        except (ValueError, TypeError, OverflowError):
            return False
    return True


def _is_numeric(series: pd.Series) -> bool:
    for v in series.dropna():
        try:
            Decimal(str(v))
        except (InvalidOperation, ValueError, TypeError):
            return False
    return True


_DATE_PATTERNS = [
    r"^\d{4}-\d{2}-\d{2}$",
    r"^\d{2}/\d{2}/\d{4}$",
    r"^\d{2}-\d{2}-\d{4}$",
]

_TIMESTAMP_PATTERNS = [
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}",
]


def _is_date(series: pd.Series) -> bool:
    for v in series.dropna():
        s = str(v).strip()
        if not any(re.match(p, s) for p in _DATE_PATTERNS):
            return False
    return len(series.dropna()) > 0


def _is_timestamp(series: pd.Series) -> bool:
    for v in series.dropna():
        s = str(v).strip()
        if not any(re.match(p, s) for p in _TIMESTAMP_PATTERNS):
            return False
    return len(series.dropna()) > 0


def _is_boolean(series: pd.Series) -> bool:
    allowed = {"true", "false", "yes", "no", "0", "1", "t", "f", "y", "n"}
    for v in series.dropna():
        if str(v).strip().lower() not in allowed:
            return False
    return len(series.dropna()) > 0


def _is_uuid(series: pd.Series) -> bool:
    for v in series.dropna():
        try:
            UUID(str(v).strip())
        except (ValueError, AttributeError):
            return False
    return len(series.dropna()) > 0


def infer_column_type(series: pd.Series) -> str:
    non_null = series.dropna()
    if len(non_null) == 0:
        return "text"
    if _is_boolean(series):
        return "boolean"
    if _is_integer(series):
        return "integer"
    if _is_numeric(series):
        return "numeric"
    if _is_timestamp(series):
        return "timestamp"
    if _is_date(series):
        return "date"
    if _is_uuid(series):
        return "uuid"
    return "text"


def infer_max_length(series: pd.Series, col_type: str) -> int | None:
    if col_type != "text":
        return None
    max_len = series.dropna().astype(str).str.len().max()
    if pd.isna(max_len) or max_len == 0:
        return 255
    max_len = int(max_len)
    if max_len <= 10:
        return 20
    if max_len <= 50:
        return 100
    if max_len <= 100:
        return 200
    if max_len <= 200:
        return 500
    return max(max_len * 2, 1000)


def detect_primary_key(df: pd.DataFrame, columns: list[dict]) -> str:
    for col in df.columns:
        name = col.lower()
        if name == "id":
            if df[col].is_unique and df[col].notna().all():
                return col
    for col in df.columns:
        name = col.lower()
        if name.endswith("_id"):
            if df[col].is_unique and df[col].notna().all():
                return col
    for col in df.columns:
        if df[col].is_unique and df[col].notna().all():
            return col
    return df.columns[0]


def detect_nullable(series: pd.Series, null_values: list[str]) -> bool:
    for v in series:
        if pd.isna(v):
            return True
        if str(v).strip() in null_values:
            return True
    return False


# ---------------------------------------------------------------------------
# Schema generation
# ---------------------------------------------------------------------------

_TYPE_MAP = {
    "integer": "INTEGER",
    "numeric": "NUMERIC(18,2)",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
    "boolean": "BOOLEAN",
    "uuid": "UUID",
}


def generate_schema_sql(table_name: str, columns: list[dict], primary_key: str) -> str:
    lines = []
    for col in columns:
        pg_type = _TYPE_MAP.get(col["type"], f"VARCHAR({col.get('max_length', 255)})")
        parts = [f"    {col['db_column']} {pg_type}"]
        if col["db_column"] == primary_key:
            parts.append("PRIMARY KEY")
        elif not col["nullable"]:
            parts.append("NOT NULL")
        lines.append(" ".join(parts))

    body = ",\n".join(lines)
    return f"CREATE TABLE IF NOT EXISTS {table_name} (\n{body}\n);\n"


# ---------------------------------------------------------------------------
# Config.yaml update
# ---------------------------------------------------------------------------


def job_exists_in_config(job_name: str) -> bool:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {"jobs": []}
    return any(j["name"] == job_name for j in config.get("jobs", []))


def append_job_to_config(job_name: str, csv_rel: str, schema_rel: str,
                         columns: list[dict], primary_key: str,
                         has_header: bool = True) -> None:
    lines = [f"\n  - name: {job_name}"]
    lines.append(f"    source_csv: {csv_rel}")
    lines.append(f"    target_table: {job_name}")
    lines.append(f"    schema_file: {schema_rel}")
    lines.append('    delimiter: ","')
    lines.append('    encoding: "utf-8"')
    lines.append(f"    has_header: {'true' if has_header else 'false'}")
    lines.append('    null_values: ["", "NULL", "N/A", "null"]')
    lines.append("")
    lines.append("    columns:")
    for col in columns:
        lines.append(f"      {col['csv_name']}:")
        lines.append(f"        db_column: {col['db_column']}")
        lines.append(f"        type: {col['type']}")
        lines.append(f"        nullable: {'true' if col['nullable'] else 'false'}")
        if col.get("max_length"):
            lines.append(f"        max_length: {col['max_length']}")
    lines.append("")
    lines.append(f"    primary_key: {primary_key}")
    lines.append("")
    lines.append("    thresholds:")
    lines.append("      max_pct_rows_dropped: 0.0")
    lines.append("      max_pct_null_in_required: 0.0")
    lines.append("      min_rows: 1")
    lines.append("")

    with CONFIG_PATH.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def create_table(sql: str, db_config) -> None:
    conn = psycopg2.connect(**db_config.connect_kwargs())
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def auto_migrate(csv_path: str | Path, dry_run: bool = False) -> int:
    csv_path = Path(csv_path).resolve()

    if not csv_path.exists():
        print(f"ERROR: File not found: {csv_path}")
        return 1

    if csv_path.suffix.lower() not in (".csv", ".tsv"):
        print(f"ERROR: Expected a .csv or .tsv file, got: {csv_path.suffix}")
        return 1

    # If the file isn't already in input_data/, copy it there
    if not str(csv_path).startswith(str(INPUT_DIR)):
        import shutil
        dest = INPUT_DIR / csv_path.name
        shutil.copy2(csv_path, dest)
        print(f"  Copied {csv_path.name} -> {INPUT_DIR}")
        csv_path = dest

    job_name = re.sub(r"[^a-z0-9_]", "_", csv_path.stem.lower())
    print(f"\n{'='*60}")
    print(f"  Auto-migrate: {csv_path.name}")
    print(f"  Job name:     {job_name}")
    print(f"  Table name:   {job_name}")
    print(f"{'='*60}\n")

    # --- Step 1: Read CSV and infer structure ---
    print("[1/5] Reading CSV and inferring column types...")
    null_values = ["", "NULL", "N/A", "null"]

    # Detect whether the first row is a header or data
    with open(csv_path, "r", encoding="utf-8") as f:
        import csv as csv_mod
        first_line = f.readline()
    first_row = next(csv_mod.reader([first_line]))
    has_header = _looks_like_header(first_row)

    if has_header:
        df = pd.read_csv(csv_path, keep_default_na=False, dtype=str)
        print("  Header row detected.")
    else:
        df = pd.read_csv(csv_path, header=None, keep_default_na=False, dtype=str)
        col_count = len(df.columns)
        df.columns = [f"col_{i+1}" for i in range(col_count)]
        print(f"  No header row detected — generated {col_count} column names (col_1, col_2, ...).")
        print("  TIP: You can rename columns later in config.yaml.")

    if df.empty:
        print("ERROR: CSV has no data rows.")
        return 1

    columns = []
    for col_name in df.columns:
        clean_name = col_name.strip().lstrip("﻿")
        db_col = re.sub(r"[^a-z0-9_]", "_", clean_name.lower())
        series = df[col_name].replace(null_values, pd.NA)
        col_type = infer_column_type(series)
        nullable = detect_nullable(df[col_name], null_values)
        max_len = infer_max_length(series, col_type)

        columns.append({
            "csv_name": clean_name,
            "db_column": db_col,
            "type": col_type,
            "nullable": nullable,
            "max_length": max_len,
        })
        print(f"    {clean_name:30s} -> {db_col:30s}  {col_type:10s}"
              f"  nullable={nullable}"
              + (f"  max_length={max_len}" if max_len else ""))

    primary_key = detect_primary_key(df, columns)
    pk_col = next(c for c in columns if c["csv_name"] == primary_key)
    pk_col["nullable"] = False
    print(f"\n  Primary key: {primary_key}")
    print(f"  Rows: {len(df)}")

    # --- Step 2: Generate schema SQL ---
    print("\n[2/5] Generating schema SQL...")
    schema_sql = generate_schema_sql(job_name, columns, pk_col["db_column"])
    schema_path = INPUT_DIR / f"{job_name}_schema.sql"
    schema_path.write_text(schema_sql, encoding="utf-8")
    print(f"  Written to: {schema_path.name}")
    print(f"  ---\n{schema_sql}  ---")

    # --- Step 3: Create table in PostgreSQL ---
    print("[3/5] Creating table in PostgreSQL...")
    db = load_db_config()
    try:
        create_table(schema_sql, db)
        print(f"  Table '{job_name}' ready.")
    except Exception as e:
        print(f"  WARNING: {e}")
        print("  Table may already exist — continuing.")

    # --- Step 4: Update config.yaml ---
    print("\n[4/5] Updating config.yaml...")
    if job_exists_in_config(job_name):
        print(f"  Job '{job_name}' already exists in config.yaml — skipping config update.")
        print("  (The existing job definition will be used for migration.)")
    else:
        csv_rel = f"./OneDrive/Desktop/Migration using ai/input_data/{csv_path.name}"
        schema_rel = f"./OneDrive/Desktop/Migration using ai/input_data/{schema_path.name}"
        append_job_to_config(job_name, csv_rel, schema_rel, columns, pk_col["db_column"],
                             has_header=has_header)
        print(f"  Job '{job_name}' added to config.yaml.")

    # --- Step 5: Run migration ---
    print(f"\n[5/5] Running migration{'  (dry-run)' if dry_run else ''}...")
    from src.config import load_jobs
    from src.migrator import run_job
    from src.reporting import Reporter

    jobs = [j for j in load_jobs(CONFIG_PATH) if j.name == job_name]
    if not jobs:
        print(f"ERROR: Job '{job_name}' not found in config after update.")
        return 1

    reporter = Reporter()
    ok = run_job(jobs[0], db, reporter, promote=not dry_run)
    reporter.write_summary()

    if ok:
        print(f"\n  Migration {'(dry-run) ' if dry_run else ''}SUCCEEDED.")
        print(f"  Table '{job_name}' now has data in PostgreSQL.")
    else:
        print("\n  Migration FAILED. Check reports/ for details.")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Auto-migrate a CSV file into PostgreSQL."
    )
    parser.add_argument("csv", help="Path to CSV file (or just the filename if in input_data/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate and stage only — don't promote to target table")
    args = parser.parse_args()

    csv_arg = args.csv
    csv_path = Path(csv_arg)
    if not csv_path.is_absolute() and not csv_path.exists():
        candidate = INPUT_DIR / csv_arg
        if candidate.exists():
            csv_path = candidate

    sys.exit(auto_migrate(csv_path, dry_run=args.dry_run))
