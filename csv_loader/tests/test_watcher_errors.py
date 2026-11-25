"""#351 (CLI-05): a failure while handling one file must not stop the watcher, and must be visible.

``CSVDropHandler._maybe_trigger`` copied the file to the job's CSV path and ran the job with no error handling. Any error
there (a file locked by Excel, a permission error, or watching the job's own input folder, which makes ``shutil.copy2``
raise ``SameFileError`` because it copies a file onto itself) escaped into watchdog's event thread. The main loop kept
sleeping, so the process looked fine while it did nothing.

What must hold:
  * an error in the copy or in the job is logged, with the file name, and does not propagate;
  * the next file is still processed after a failure (shown with a real watchdog observer, not only by calling the
    handler);
  * watching the folder that holds the job's own CSV works: the file is already where the job expects it, so no copy is
    made and the job runs (``SameFileError`` used to be raised on every file);
  * the operator sees the failure: an ERROR log line naming the file, with the traceback.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest
from watchdog.observers import Observer

import src.watcher as watcher
from src.config import ColumnSpec, JobConfig, Thresholds
from src.reporting import Reporter

pytestmark = pytest.mark.unit


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)

    def errors(self) -> list[str]:
        return [r.getMessage() for r in self.records if r.levelno >= logging.ERROR]


def make_job(name: str, source: Path) -> JobConfig:
    return JobConfig(
        name=name, source_csv=source, target_table=name, schema_file=source.with_suffix(".sql"), delimiter=",",
        encoding="utf-8", has_header=True, null_values=[""], columns=[ColumnSpec("id", "id", "integer", nullable=False)],
        primary_key="id", thresholds=Thresholds(min_rows=1))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """A handler with two jobs (a.csv, b.csv), a watched folder, a separate folder the jobs read from, and a capture."""
    incoming, jobs_dir = tmp_path / "incoming", tmp_path / "jobs"
    incoming.mkdir(), jobs_dir.mkdir()
    jobs = {"a.csv": make_job("a", jobs_dir / "a.csv"), "b.csv": make_job("b", jobs_dir / "b.csv")}
    reporter = Reporter()
    capture = Capture()
    reporter.logger.addHandler(capture)
    handler = watcher.CSVDropHandler(jobs, reporter)
    ran: list[str] = []
    monkeypatch.setattr(watcher, "run_job", lambda job, db, rep, promote=True: ran.append(job.name) or True)
    monkeypatch.setattr(watcher, "_STABLE_INTERVAL_S", 0.05)
    yield handler, incoming, jobs_dir, capture, ran
    reporter.logger.removeHandler(capture)


def drop(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_text("id\n1\n", encoding="utf-8")
    return path


def test_a_failing_copy_is_logged_with_the_file_name_and_does_not_propagate(setup, monkeypatch):
    handler, incoming, _, capture, ran = setup

    def locked(*_a, **_k):
        raise PermissionError("file is locked by another process")
    monkeypatch.setattr(watcher.shutil, "copy2", locked)
    handler._maybe_trigger(str(drop(incoming, "a.csv")))      # must not raise
    assert ran == [], "the job must not run on a file that could not be copied"
    errors = capture.errors()
    assert any("a.csv" in m and "locked" in m for m in errors), errors


def test_a_failing_job_is_logged_with_the_file_name_and_does_not_propagate(setup, monkeypatch):
    handler, incoming, _, capture, _ = setup

    def boom(*_a, **_k):
        raise RuntimeError("database went away")
    monkeypatch.setattr(watcher, "run_job", boom)
    handler._maybe_trigger(str(drop(incoming, "b.csv")))
    assert any("b.csv" in m and "database went away" in m for m in capture.errors()), capture.errors()


def test_the_error_log_carries_the_traceback(setup, monkeypatch):
    handler, incoming, _, capture, _ = setup
    monkeypatch.setattr(watcher.shutil, "copy2", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    handler._maybe_trigger(str(drop(incoming, "a.csv")))
    assert any(r.exc_info for r in capture.records if r.levelno >= logging.ERROR), "log the exception, not just a message"


def test_watching_the_jobs_own_input_folder_runs_the_job_without_copying_a_file_onto_itself(setup):
    handler, _, jobs_dir, capture, ran = setup
    handler._maybe_trigger(str(drop(jobs_dir, "a.csv")))      # the dropped file IS the job's source_csv
    assert ran == ["a"], capture.errors()
    assert capture.errors() == []


def test_a_second_file_after_a_failure_is_still_processed_by_a_real_observer(setup, monkeypatch):
    handler, incoming, jobs_dir, capture, ran = setup
    real_copy = watcher.shutil.copy2
    calls = {"n": 0}

    def flaky_copy(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked by Excel")
        return real_copy(src, dst, *a, **k)
    monkeypatch.setattr(watcher.shutil, "copy2", flaky_copy)

    observer = Observer()
    observer.schedule(handler, str(incoming), recursive=False)
    observer.start()
    try:
        drop(incoming, "a.csv")                                # first file: the copy fails
        deadline = time.time() + 10
        while time.time() < deadline and not capture.errors():
            time.sleep(0.05)
        assert any("a.csv" in m for m in capture.errors()), "the first failure was not logged"
        drop(incoming, "b.csv")                                # second file: must still be handled
        deadline = time.time() + 10
        while time.time() < deadline and "b" not in ran:
            time.sleep(0.05)
        assert "b" in ran, f"the watcher stopped after the first failure (ran={ran}, errors={capture.errors()})"
        assert observer.is_alive(), "the observer thread died"
    finally:
        observer.stop()
        observer.join(timeout=5)
