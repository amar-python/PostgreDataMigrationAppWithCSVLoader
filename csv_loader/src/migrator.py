"""Migration orchestrator.

Wires the pipeline together: pre-import → schema → ingestion → integrity →
optional promotion. Every stage feeds the Reporter, and a failing stage
short-circuits before any data lands in the target table.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterable

import psycopg2

from .config import DBConfig, JobConfig, load_db_config, load_jobs
from .ingestion import load_csv_to_staging, promote_staging_to_target
from .integrity_checks import run_integrity_checks
from .pre_import_validator import validate_csv
from .reporting import Reporter
from .schema_validator import ensure_staging_table, validate_schema


@contextmanager
def _connect(db: DBConfig):
    """Open a psycopg2 connection and *guarantee* it's closed on exit.

    BUG-05: psycopg2's own ``with`` handles transactions but does not close
    the connection. Wrap that behaviour ourselves so long-running orchestrators
    (the watcher loop, batch runs) don't leak connections.
    """
    conn = psycopg2.connect(**db.connect_kwargs())
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def run_job(
    job: JobConfig,
    db: DBConfig,
    reporter: Reporter,
    *,
    promote: bool = True,
) -> bool:
    """Run a single job. Returns True if the job succeeded end-to-end."""
    log = reporter.logger
    report = reporter.new_job(job.name)
    log.info("=== Starting job: %s ===", job.name)

    # Stage 1: Pre-import (no DB needed).
    # BUG-02: any unexpected exception here must be captured as a clean
    # failed stage rather than escaping the orchestrator.
    try:
        pre, csv_df = validate_csv(job)
    except Exception as exc:  # noqa: BLE001
        report.error = f"Pre-import crashed: {type(exc).__name__}: {exc}"
        log.exception("Pre-import crashed for %s", job.name)
        reporter.finalize_job(report)
        return False

    report.add_stage(pre)
    if not pre.passed:
        report.error = "Pre-import validation failed"
        log.error("Pre-import failed for %s", job.name)
        reporter.finalize_job(report)
        return False

    row_count_metric = next(
        (c.metric for c in pre.checks if c.name == "row_shape_consistent"),
        None,
    )
    if row_count_metric:
        report.rows_in_csv = row_count_metric.get("row_count", 0)

    # Stage 2+: DB-bound
    try:
        with _connect(db) as conn:
            schema = validate_schema(conn, job)
            report.add_stage(schema)
            if not schema.passed:
                report.error = "Schema validation failed"
                log.error("Schema mismatch for %s", job.name)
                reporter.finalize_job(report)
                return False

            ensure_staging_table(conn, job)
            log.info("Staging table %s ready", job.staging_table)

            csv_rows, staging_rows = load_csv_to_staging(conn, job)
            report.rows_in_staging = staging_rows
            log.info(
                "Loaded %s -> %s: csv=%d staging=%d",
                job.source_csv, job.staging_table, csv_rows, staging_rows,
            )

            integrity = run_integrity_checks(conn, job, csv_df, staging_rows)
            report.add_stage(integrity)
            if not integrity.passed:
                report.error = "Integrity audit failed"
                log.error(
                    "Integrity failures for %s; refusing to promote", job.name
                )
                reporter.finalize_job(report)
                return False

            if promote:
                target_count = promote_staging_to_target(conn, job)
                report.rows_in_target = target_count
                if target_count < staging_rows:
                    report.error = (
                        f"Post-promotion row count mismatch: "
                        f"staging={staging_rows}, target={target_count}"
                    )
                    log.error(
                        "Promotion lost rows for %s: staging=%d target=%d",
                        job.name, staging_rows, target_count,
                    )
                    reporter.finalize_job(report)
                    return False
                log.info(
                    "Promoted %s into %s; target now has %d rows",
                    job.staging_table, job.target_table, target_count,
                )
            else:
                log.info("Promotion skipped for %s (dry-run)", job.name)

    except Exception as exc:  # noqa: BLE001
        report.error = f"{type(exc).__name__}: {exc}"
        log.exception("Job %s aborted with exception", job.name)
        reporter.finalize_job(report)
        return False

    reporter.finalize_job(report)
    return True


def run_all(
    jobs: Iterable[JobConfig] | None = None,
    db: DBConfig | None = None,
    *,
    promote: bool = True,
    config_path: str = "config.yaml",
) -> Reporter:
    """Run every configured job. Returns the Reporter for inspection."""
    db = db or load_db_config()
    jobs = list(jobs) if jobs is not None else load_jobs(config_path)
    reporter = Reporter()
    reporter.logger.info("Run %s starting (%d jobs)", reporter.run_id, len(jobs))

    for job in jobs:
        run_job(job, db, reporter, promote=promote)

    reporter.write_summary()
    return reporter
