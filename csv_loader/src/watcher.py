"""Directory watcher.

Triggers a migration job when a CSV matching a known job's `source_csv`
filename appears in the watched directory. Uses `watchdog` so it works on
Linux, macOS, and Windows.
"""
from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Dict

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import JobConfig, load_db_config, load_jobs
from .migrator import run_job
from .reporting import Reporter


# How long a file's size must remain unchanged before we consider the writer
# done. Polled in 250 ms intervals; each new size resets the clock.
_STABLE_INTERVAL_S = 0.25
_STABLE_TIMEOUT_S = 30.0

# Re-trigger debounce window. on_created and on_modified often fire close
# together for the same file; we collapse those into a single run.
_DEBOUNCE_WINDOW_S = 1.5


def _wait_for_stable_size(path: Path) -> bool:
    """Poll until the file size stops changing. Returns True if stable."""
    deadline = time.time() + _STABLE_TIMEOUT_S
    last_size = -1
    last_change = time.time()
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size != last_size:
            last_size = size
            last_change = time.time()
        elif time.time() - last_change >= _STABLE_INTERVAL_S:
            return True
        time.sleep(_STABLE_INTERVAL_S)
    return False


class CSVDropHandler(FileSystemEventHandler):
    """Match dropped CSVs against configured jobs by filename.

    BUG-16: subscribes to both ``on_created`` and ``on_modified`` so files
    written by ``mv`` from another mount (which only emits modified) are
    handled too.
    BUG-17: waits for the file size to stop changing before firing — protects
    against partial reads of large files.
    """

    def __init__(
        self, jobs_by_filename: Dict[str, JobConfig], reporter: Reporter
    ):
        self.jobs_by_filename = jobs_by_filename
        self.reporter = reporter
        self.db = load_db_config()
        self._lock = threading.Lock()
        self._recent: Dict[str, float] = {}

    def _should_handle(self, path: Path) -> bool:
        with self._lock:
            now = time.time()
            # Drop entries older than the debounce window.
            stale = [k for k, t in self._recent.items()
                     if now - t > _DEBOUNCE_WINDOW_S]
            for k in stale:
                self._recent.pop(k, None)

            key = str(path.resolve())
            if key in self._recent:
                return False
            self._recent[key] = now
            return True

    def _maybe_trigger(self, src_path: str) -> None:
        """Handle one file event. Never raises: an error is logged and the watcher goes on (#351).

        An exception that escapes a watchdog handler ends the observer's event thread, while the main loop keeps
        sleeping, so the process looks healthy and does nothing. (Reproduced with watchdog 7.1.1: the thread dies with
        the handler's exception.) A locked file, a permission error or a database that went away must cost one file,
        not the watcher.
        """
        try:
            self._handle_file(Path(src_path))
        except Exception as exc:  # noqa: BLE001 - the point is that nothing may escape into watchdog's thread
            self.reporter.logger.exception(
                "Watcher failed on %s (%s: %s); it keeps watching", src_path, type(exc).__name__, exc,
            )

    def _handle_file(self, path: Path) -> None:
        job = self.jobs_by_filename.get(path.name)
        if not job:
            return  # Silently ignore files we have no job for.

        if not self._should_handle(path):
            return

        if not _wait_for_stable_size(path):
            self.reporter.logger.warning(
                "File %s did not stabilize within %.0fs; skipping",
                path, _STABLE_TIMEOUT_S,
            )
            return

        # Copy to the configured source location and trigger the job. When the watched folder is the one that holds the
        # job's CSV, the dropped file already is the source: copying it onto itself raised SameFileError on every file.
        target = Path(job.source_csv)
        if path.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        self.reporter.logger.info(
            "Triggering job %s for incoming file %s", job.name, path.name
        )
        run_job(job, self.db, self.reporter, promote=True)

    # watchdog hooks --------------------------------------------------------
    def on_created(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        self._maybe_trigger(event.src_path)

    def on_modified(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        self._maybe_trigger(event.src_path)

    def on_moved(self, event):  # type: ignore[override]
        if event.is_directory:
            return
        # mv into the watched dir surfaces as on_moved with dest_path set.
        dest = getattr(event, "dest_path", None)
        if dest:
            self._maybe_trigger(dest)


def watch(directory: str | Path, config_path: str = "config.yaml") -> None:
    jobs = load_jobs(config_path)
    jobs_by_filename = {Path(j.source_csv).name: j for j in jobs}
    reporter = Reporter()
    reporter.logger.info(
        "Watching %s for CSVs matching: %s",
        directory, sorted(jobs_by_filename.keys()),
    )

    Path(directory).mkdir(parents=True, exist_ok=True)
    handler = CSVDropHandler(jobs_by_filename, reporter)
    observer = Observer()
    observer.schedule(handler, str(directory), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        reporter.write_summary()
        reporter.logger.info("Watcher stopped, summary written")
    observer.join()
