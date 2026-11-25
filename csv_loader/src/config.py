"""Configuration loader.

Reads `config.yaml` for migration job definitions and merges in PostgreSQL
connection details from environment variables (`.env` supported via
python-dotenv).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ColumnSpec:
    """Specification for a single column in a migration job."""
    csv_name: str
    db_column: str
    type: str
    nullable: bool = True
    max_length: Optional[int] = None
    unique: bool = False


@dataclass
class SpotCheck:
    """A single row-level assertion run after migration."""
    row_match: Dict[str, Any]
    assert_values: Dict[str, Any]


@dataclass
class Thresholds:
    max_pct_rows_dropped: float = 0.0
    max_pct_null_in_required: float = 0.0
    # BUG-20: empty-CSV detection. 0 means "don't check"; positive int means
    # the load must produce at least that many rows or the stage fails.
    min_rows: int = 0


@dataclass
class JobConfig:
    name: str
    source_csv: Path
    target_table: str
    schema_file: Path
    delimiter: str
    encoding: str
    has_header: bool
    null_values: List[str]
    columns: List[ColumnSpec]
    primary_key: str
    spot_checks: List[SpotCheck] = field(default_factory=list)
    thresholds: Thresholds = field(default_factory=Thresholds)

    @property
    def staging_table(self) -> str:
        return f"{self.target_table}_staging"

    @property
    def required_columns(self) -> List[ColumnSpec]:
        return [c for c in self.columns if not c.nullable]

    # BUG-03: separate the CSV-side name and the DB-side name of the primary
    # key. We accept `primary_key` in the YAML as either the CSV column name
    # or the DB column name (whichever the user wrote) — we resolve to a
    # ColumnSpec and expose both halves.
    @property
    def primary_key_spec(self) -> ColumnSpec:
        for c in self.columns:
            if c.csv_name == self.primary_key or c.db_column == self.primary_key:
                return c
        raise KeyError(
            f"primary_key '{self.primary_key}' is not declared in columns"
        )

    @property
    def primary_key_csv(self) -> str:
        return self.primary_key_spec.csv_name

    @property
    def primary_key_db(self) -> str:
        return self.primary_key_spec.db_column


@dataclass
class DBConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    sslmode: str = "prefer"

    def connect_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "dbname": self.database,
            "user": self.user,
            "password": self.password,
        }
        if self.sslmode and self.sslmode != "disable":
            kwargs["sslmode"] = self.sslmode
        return kwargs


def load_db_config() -> DBConfig:
    return DBConfig(
        host=os.getenv("PG_HOST", "localhost"),
        port=int(os.getenv("PG_PORT", "5432")),
        database=os.getenv("PG_DATABASE", "migration_test"),
        user=os.getenv("PG_USER", "postgres"),
        password=os.getenv("PG_PASSWORD", ""),
        sslmode=os.getenv("PG_SSLMODE", "prefer"),
    )


def load_jobs(config_path: str | Path = "config.yaml") -> List[JobConfig]:
    """Parse the YAML config and return a list of JobConfig objects.

    Relative `source_csv` and `schema_file` paths are resolved against the
    config file's directory so the loader does not depend on the caller's
    current working directory (BUG-13).
    """
    config_path = Path(config_path).resolve()
    base_dir = config_path.parent

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    def _resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (base_dir / path).resolve()

    jobs: List[JobConfig] = []
    for j in raw.get("jobs", []):
        columns = [
            ColumnSpec(
                csv_name=csv_name,
                db_column=spec["db_column"],
                type=spec["type"],
                nullable=spec.get("nullable", True),
                max_length=spec.get("max_length"),
                unique=spec.get("unique", False),
            )
            for csv_name, spec in j["columns"].items()
        ]

        spot_checks = [
            SpotCheck(row_match=sc["row_match"], assert_values=sc["assert"])
            for sc in j.get("spot_checks", [])
        ]

        thresholds_raw = j.get("thresholds", {})
        thresholds = Thresholds(
            max_pct_rows_dropped=thresholds_raw.get("max_pct_rows_dropped", 0.0),
            max_pct_null_in_required=thresholds_raw.get(
                "max_pct_null_in_required", 0.0
            ),
            min_rows=thresholds_raw.get("min_rows", 0),
        )

        jobs.append(
            JobConfig(
                name=j["name"],
                source_csv=_resolve(j["source_csv"]),
                target_table=j["target_table"],
                schema_file=_resolve(j["schema_file"]),
                delimiter=j.get("delimiter", ","),
                encoding=j.get("encoding", "utf-8"),
                has_header=j.get("has_header", True),
                null_values=j.get("null_values", [""]),
                columns=columns,
                primary_key=j["primary_key"],
                spot_checks=spot_checks,
                thresholds=thresholds,
            )
        )
    return jobs


def get_job(name: str, config_path: str | Path = "config.yaml") -> JobConfig:
    for job in load_jobs(config_path):
        if job.name == name:
            return job
    raise KeyError(f"Job not found: {name}")
