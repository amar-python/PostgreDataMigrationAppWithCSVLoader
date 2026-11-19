"""#273: scripts/test_report.py can account for tests outside pytest.ini's testpaths (the browser tests in e2e/).

Until now it ran pytest with no path, so it could only see tests/ and the browser tier was invisible to its final
block and to --strict. `--paths` hands the same paths to the collection pass and to the run.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def report(monkeypatch):
    spec = importlib.util.spec_from_file_location("test_report_script", ROOT / "scripts" / "test_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls: list[list[str]] = []

    class Done:
        returncode = 0
        stdout = ""

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return Done()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    module.calls = calls
    return module


def test_without_paths_pytest_gets_no_path_so_testpaths_applies(report, tmp_path):
    report._run("unit", tmp_path / "r.xml")
    report._collect_all_ids()

    run_cmd, collect_cmd = report.calls
    assert run_cmd[-2:] == ["-m", "unit"]
    assert collect_cmd[-2:] == ["-o", "addopts="]


def test_paths_reach_the_run_and_the_collection_pass(report, tmp_path):
    report._run(None, tmp_path / "r.xml", ["e2e"])
    report._collect_all_ids(["e2e"])

    run_cmd, collect_cmd = report.calls
    # `python -m pytest` carries one -m already; a second one would be a marker filter.
    assert run_cmd[-1] == "e2e" and run_cmd.count("-m") == 1
    assert collect_cmd[-1] == "e2e" and "--collect-only" in collect_cmd


def test_paths_and_markers_combine(report, tmp_path):
    report._run("not slow", tmp_path / "r.xml", ["e2e", "tests/unit"])

    cmd = report.calls[0]
    assert cmd[cmd.index("not slow") - 1] == "-m"
    assert cmd[-2:] == ["e2e", "tests/unit"]


def test_the_command_line_option_is_passed_through(report, monkeypatch, tmp_path):
    seen: dict = {}
    monkeypatch.setattr(report, "_collect_all_ids", lambda paths=None: seen.setdefault("collect", paths) or set())
    monkeypatch.setattr(report, "_run", lambda markers, xml, paths=None: seen.setdefault("run", paths) or 0)
    monkeypatch.setattr(sys, "argv", ["test_report.py", "--paths", "e2e", "--strict"])

    assert report.main() == 0
    assert seen == {"collect": ["e2e"], "run": ["e2e"]}


def test_a_skip_still_fails_a_strict_run_on_the_browser_tier(report, monkeypatch):
    monkeypatch.setattr(report, "_collect_all_ids", lambda paths=None: {"e2e/test_x.py::test_a"})
    monkeypatch.setattr(report, "_run", lambda markers, xml, paths=None: 0)
    monkeypatch.setattr(report, "_parse", lambda xml: ([], [], [], [("e2e.test_x::test_a", "no browser")]))
    monkeypatch.setattr(sys, "argv", ["test_report.py", "--paths", "e2e", "--strict"])

    assert report.main() == 1
