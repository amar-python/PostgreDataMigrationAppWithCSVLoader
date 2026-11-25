"""Unit tests for src/migrator.py — covers BUG-02 (clean failure on
unhandled pre-import exception) and the connection-leak guard from BUG-05.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import ColumnSpec, DBConfig, JobConfig, Thresholds
from src.migrator import run_job
from src.reporting import Reporter


pytestmark = pytest.mark.unit


def _job(source_csv: Path) -> JobConfig:
    return JobConfig(
        name="t",
        source_csv=source_csv,
        target_table="users",
        schema_file=Path("/tmp/x.sql"),
        delimiter=",", encoding="utf-8", has_header=True,
        null_values=[""],
        columns=[ColumnSpec("id", "id", "integer", nullable=False)],
        primary_key="id",
        spot_checks=[],
        thresholds=Thresholds(),
    )


def test_bug02_pre_import_exception_records_clean_failure(tmp_path):
    """If validate_csv raises, run_job records a failed report and returns
    False — it must not propagate the exception."""
    job = _job(tmp_path / "missing.csv")
    db = DBConfig("h", 5432, "d", "u", "p")
    reporter = Reporter()

    boom = RuntimeError("simulated parser explosion")
    with patch("src.migrator.validate_csv", side_effect=boom):  # raises before returning tuple
        ok = run_job(job, db, reporter, promote=True)

    assert ok is False
    assert len(reporter.job_reports) == 1
    report = reporter.job_reports[0]
    assert report.success is False
    assert report.error is not None
    assert "simulated parser explosion" in report.error
    # finalize_job must have been called so a JSON artifact exists.
    json_path = reporter.run_dir / f"{job.name}.json"
    assert json_path.exists()


def test_bug05_connection_closed_on_normal_exit(tmp_path):
    """The migrator's _connect context manager should close the connection."""
    from src.migrator import _connect
    fake_conn = MagicMock()
    with patch("src.migrator.psycopg2.connect", return_value=fake_conn):
        db = DBConfig("h", 5432, "d", "u", "p")
        with _connect(db) as c:
            assert c is fake_conn
        fake_conn.close.assert_called_once()


def test_bug05_connection_closed_on_exception(tmp_path):
    """The connection should still be closed if the body raises."""
    from src.migrator import _connect
    fake_conn = MagicMock()
    with patch("src.migrator.psycopg2.connect", return_value=fake_conn):
        db = DBConfig("h", 5432, "d", "u", "p")
        with pytest.raises(RuntimeError):
            with _connect(db):
                raise RuntimeError("boom")
        fake_conn.close.assert_called_once()
