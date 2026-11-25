"""Unit tests for src/watcher.py — covers BUG-16 and BUG-17."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from src.watcher import _wait_for_stable_size


pytestmark = pytest.mark.unit


def test_bug17_wait_for_stable_returns_true_for_static_file(tmp_path: Path):
    """Given an existing file that is not being written to, _wait_for_stable_size should return True immediately."""
    p = tmp_path / "fixed.csv"
    p.write_text("id\n1\n", encoding="utf-8")
    assert _wait_for_stable_size(p) is True


def test_bug17_wait_for_stable_returns_false_for_missing_file(tmp_path: Path):
    """Given a path that does not exist, _wait_for_stable_size should return False without raising."""
    p = tmp_path / "missing.csv"
    assert _wait_for_stable_size(p) is False


def test_bug17_wait_for_stable_waits_until_writes_stop(tmp_path: Path):
    """Simulate a slow writer: file grows for ~0.6 s then stops."""
    p = tmp_path / "growing.csv"
    p.write_text("id\n", encoding="utf-8")

    stop_event = threading.Event()

    def grow():
        # Append every 100 ms for ~0.6 s, then stop.
        deadline = time.time() + 0.6
        i = 0
        while time.time() < deadline and not stop_event.is_set():
            with p.open("a", encoding="utf-8") as f:
                f.write(f"{i}\n")
            i += 1
            time.sleep(0.1)

    t = threading.Thread(target=grow)
    t.start()
    try:
        # _wait_for_stable_size should not return until the writer is done.
        start = time.time()
        result = _wait_for_stable_size(p)
        elapsed = time.time() - start
    finally:
        stop_event.set()
        t.join(timeout=2)

    assert result is True
    # Must have waited at least the time the writer was active.
    assert elapsed >= 0.5
