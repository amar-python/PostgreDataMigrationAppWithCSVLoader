"""Unit tests for src/config.py — covers regressions BUG-03, BUG-07, BUG-13."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from src.config import DBConfig, JobConfig, Thresholds, load_jobs


pytestmark = pytest.mark.unit


# --------------------- BUG-03: primary-key remap -----------------------------

def test_primary_key_resolves_to_csv_and_db_names_when_equal():
    """When csv_name and db_column are both 'id', primary_key_csv and primary_key_db should both resolve to 'id'."""
    job = JobConfig(
        name="t",
        source_csv=Path("/tmp/x.csv"),
        target_table="t",
        schema_file=Path("/tmp/x.sql"),
        delimiter=",", encoding="utf-8", has_header=True,
        null_values=[""],
        columns=[],  # filled below via dataclass replace? simpler: build by hand
        primary_key="id",
    )
    # Re-build with proper columns
    from src.config import ColumnSpec
    job.columns = [
        ColumnSpec("id", "id", "integer", nullable=False),
        ColumnSpec("email", "email", "text", nullable=False),
    ]
    assert job.primary_key_csv == "id"
    assert job.primary_key_db == "id"


def test_primary_key_resolves_when_csv_and_db_differ():
    """primary_key 'user_id' in YAML may point at csv_name='user_id', db_column='id'."""
    from src.config import ColumnSpec
    job = JobConfig(
        name="t",
        source_csv=Path("/tmp/x.csv"),
        target_table="t",
        schema_file=Path("/tmp/x.sql"),
        delimiter=",", encoding="utf-8", has_header=True,
        null_values=[""],
        columns=[
            ColumnSpec("user_id", "id", "integer", nullable=False),
            ColumnSpec("email", "email", "text", nullable=False),
        ],
        primary_key="user_id",
    )
    assert job.primary_key_csv == "user_id"
    assert job.primary_key_db == "id"


def test_primary_key_resolves_when_user_writes_db_name():
    """primary_key may equally be the db_column name."""
    from src.config import ColumnSpec
    job = JobConfig(
        name="t",
        source_csv=Path("/tmp/x.csv"),
        target_table="t",
        schema_file=Path("/tmp/x.sql"),
        delimiter=",", encoding="utf-8", has_header=True,
        null_values=[""],
        columns=[
            ColumnSpec("user_id", "id", "integer", nullable=False),
            ColumnSpec("email", "email", "text", nullable=False),
        ],
        primary_key="id",  # using DB name here
    )
    assert job.primary_key_csv == "user_id"
    assert job.primary_key_db == "id"


def test_primary_key_invalid_raises():
    """When primary_key names a column absent from both csv_name and db_column, accessing primary_key_db should raise KeyError."""
    from src.config import ColumnSpec
    job = JobConfig(
        name="t",
        source_csv=Path("/tmp/x.csv"),
        target_table="t",
        schema_file=Path("/tmp/x.sql"),
        delimiter=",", encoding="utf-8", has_header=True,
        null_values=[""],
        columns=[ColumnSpec("id", "id", "integer", nullable=False)],
        primary_key="nope",
    )
    with pytest.raises(KeyError):
        _ = job.primary_key_db


def test_connect_kwargs_returns_correct_keys():
    """DBConfig.connect_kwargs() should return the five psycopg2 keys (host/port/dbname/user/password) plus sslmode."""
    db = DBConfig("h", 5433, "d", "u", "p")
    kw = db.connect_kwargs()
    assert kw == {"host": "h", "port": 5433, "dbname": "d", "user": "u", "password": "p", "sslmode": "prefer"}


# --------------------- BUG-13: config-relative path resolution --------------

def test_load_jobs_resolves_paths_relative_to_config(tmp_path: Path):
    """load_jobs should not depend on the caller's CWD."""
    (tmp_path / "data").mkdir()
    csv_file = tmp_path / "data" / "users.csv"
    csv_file.write_text("id,email\n1,a@x.com\n", encoding="utf-8")
    sql_file = tmp_path / "data" / "users.sql"
    sql_file.write_text("CREATE TABLE users(id int, email text);", encoding="utf-8")

    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        jobs:
          - name: users
            source_csv: ./data/users.csv
            target_table: users
            schema_file: ./data/users.sql
            primary_key: id
            columns:
              id:
                db_column: id
                type: integer
                nullable: false
              email:
                db_column: email
                type: text
                nullable: false
    """).strip(), encoding="utf-8")

    # Run from a different cwd to ensure resolution is config-relative.
    import os
    saved_cwd = os.getcwd()
    try:
        os.chdir(str(tmp_path.parent))
        jobs = load_jobs(cfg)
    finally:
        os.chdir(saved_cwd)

    assert len(jobs) == 1
    assert jobs[0].source_csv == csv_file.resolve()
    assert jobs[0].schema_file == sql_file.resolve()


def test_load_jobs_picks_up_min_rows_threshold(tmp_path: Path):
    """A YAML job with thresholds.min_rows set should deserialize into Thresholds.min_rows on the loaded job."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(textwrap.dedent("""
        jobs:
          - name: t
            source_csv: ./x.csv
            target_table: t
            schema_file: ./x.sql
            primary_key: id
            thresholds:
              min_rows: 10
            columns:
              id:
                db_column: id
                type: integer
                nullable: false
    """).strip(), encoding="utf-8")
    jobs = load_jobs(cfg)
    assert jobs[0].thresholds.min_rows == 10
