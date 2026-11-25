"""End-to-end test: CSV -> staging -> integrity -> promotion -> target."""
from __future__ import annotations

import pytest

from src.migrator import run_job
from src.config import load_db_config
from src.reporting import Reporter


@pytest.mark.integration
def test_end_to_end_users_job_succeeds(
    pg_conn, users_job, fresh_target_table
):
    """Given fresh_target_table and sample_data/users.csv (10 rows), run_job with promote=True should copy all rows to the target table (count == 10)."""
    db = load_db_config()
    reporter = Reporter()
    ok = run_job(users_job, db, reporter, promote=True)
    reporter.write_summary()

    assert ok, [
        (s.stage, [c.detail for c in s.checks if not c.passed])
        for s in reporter.job_reports[0].stages
        if not s.passed
    ]

    # Confirm the target really got the rows
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{users_job.target_table}"')
        count = cur.fetchone()[0]
    assert count == 10, f"Expected 10 rows in target, got {count}"


@pytest.mark.integration
def test_dry_run_does_not_promote(
    pg_conn, users_job, fresh_target_table
):
    """Given fresh_target_table, run_job with promote=False should populate staging (10 rows from sample_data/users.csv) but leave the target table empty."""
    db = load_db_config()
    reporter = Reporter()
    ok = run_job(users_job, db, reporter, promote=False)
    assert ok

    # Staging populated, target empty
    with pg_conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM "{users_job.staging_table}"')
        staging_count = cur.fetchone()[0]
        cur.execute(f'SELECT COUNT(*) FROM "{users_job.target_table}"')
        target_count = cur.fetchone()[0]

    assert staging_count == 10
    assert target_count == 0
