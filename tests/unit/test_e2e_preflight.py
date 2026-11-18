"""e2e/preflight.py: the browser tests say what is missing, all of it, before they start anything slow.

The motivating failures: Playwright's Python package expecting a browser build that is not installed (a
cryptic "Executable doesn't exist" trace), PostgreSQL not running, and a package version read from an
attribute the package does not have. No Playwright, browser or database is needed here.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]

PATH = Path(__file__).resolve().parents[2] / "e2e" / "preflight.py"
spec = importlib.util.spec_from_file_location("e2e_preflight", PATH)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)

UP = lambda host, port: (True, "")  # noqa: E731
FREE = lambda port: True  # noqa: E731


def _all_fine(tmp_path, **overrides):
    (tmp_path / "csv-table-hub-main" / "node_modules").mkdir(parents=True)
    args = dict(root=tmp_path, env={}, pg_host="localhost", pg_port=5433, probe=UP, ports=(8000, 8080),
                is_free=FREE)
    args.update(overrides)
    return preflight.problems(**args)


# ── Playwright ────────────────────────────────────────────────────────────────────────────

def test_a_missing_playwright_says_how_to_install_it(monkeypatch):
    def not_installed(name):
        raise preflight.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(preflight.importlib.metadata, "version", not_installed)

    msg = preflight.check_playwright()

    assert "not installed" in msg and "pip install playwright" in msg and "playwright install chromium" in msg


def test_playwright_is_asked_of_the_package_metadata_not_of_a_version_attribute(monkeypatch):
    """The original failure: `playwright.__version__` raises AttributeError, because the package has none."""
    bare = types.ModuleType("playwright")  # importable, with no __version__
    monkeypatch.setitem(sys.modules, "playwright", bare)
    monkeypatch.setattr(preflight.importlib.metadata, "version", lambda name: "1.2.3")

    assert not hasattr(bare, "__version__")
    assert preflight.check_playwright() is None


# ── the browser ───────────────────────────────────────────────────────────────────────────

def test_an_override_that_points_nowhere_is_reported_with_the_way_out(tmp_path):
    missing = tmp_path / "no" / "chrome"

    msg = preflight.check_browser({"E2E_CHROMIUM": str(missing)})

    assert str(missing) in msg and "E2E_CHROMIUM" in msg and "playwright install chromium" in msg


def test_an_override_that_exists_and_no_override_are_both_fine(tmp_path):
    here = tmp_path / "chrome"
    here.write_text("")

    assert preflight.check_browser({"E2E_CHROMIUM": str(here)}) is None
    assert preflight.check_browser({}) is None, "Playwright's own browser is checked when it is launched"
    assert preflight.check_browser({"E2E_CHROMIUM": ""}) is None


# ── PostgreSQL ────────────────────────────────────────────────────────────────────────────

def test_postgresql_not_there_names_where_it_looked_why_and_what_to_do():
    msg = preflight.check_postgres("db.example.test", 6543, lambda h, p: (False, "refused"))

    assert "db.example.test:6543" in msg and "refused" in msg
    assert "PGHOST" in msg and "PGPORT" in msg and "deploy_all.sh dev" in msg


def test_the_probe_is_asked_about_the_host_and_port_it_was_given_as_text():
    asked = []
    preflight.check_postgres("h", 5433, lambda host, port: asked.append((host, port)) or (True, ""))
    assert asked == [("h", "5433")]


def test_postgresql_there_is_fine():
    assert preflight.check_postgres("localhost", 5433, UP) is None


# ── ports, Node, Streamlit ────────────────────────────────────────────────────────────────

def test_every_busy_port_is_listed_with_the_remedy():
    msgs = preflight.check_ports((8000, 8080, 8501), lambda p: p == 8080)

    assert [m.split(" is in use")[0] for m in msgs] == ["port 8000", "port 8501"]
    assert all("stop whatever listens on it" in m for m in msgs)


def test_missing_node_modules_says_npm_ci(tmp_path):
    assert "npm ci" in preflight.check_node_modules(tmp_path)
    (tmp_path / "csv-table-hub-main" / "node_modules").mkdir(parents=True)
    assert preflight.check_node_modules(tmp_path) is None


def test_a_missing_streamlit_says_how_to_install_it(monkeypatch):
    monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda name: None)
    assert "streamlit_app/requirements.txt" in preflight.check_streamlit()


# ── all together ──────────────────────────────────────────────────────────────────────────

def test_nothing_is_reported_when_everything_is_there(tmp_path):
    assert _all_fine(tmp_path) == []


def test_every_problem_is_reported_at_once_in_a_stable_order(tmp_path, monkeypatch):
    def not_installed(name):
        raise preflight.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(preflight.importlib.metadata, "version", not_installed)
    monkeypatch.setattr(preflight.importlib.util, "find_spec", lambda name: None)  # Streamlit missing too
    found = preflight.problems(root=tmp_path, env={"E2E_CHROMIUM": str(tmp_path / "gone")}, pg_host="h",
                               pg_port=1, probe=lambda h, p: (False, "refused"), ports=(8000, 8080),
                               is_free=lambda p: p != 8080)

    assert len(found) == 6
    assert [m.split(" ")[0] for m in found][:3] == ["Playwright", "E2E_CHROMIUM", "Streamlit"]
    assert "npm ci" in found[3] and "PostgreSQL" in found[4] and "port 8080" in found[5]
    assert found == preflight.problems(root=tmp_path, env={"E2E_CHROMIUM": str(tmp_path / "gone")}, pg_host="h",
                                       pg_port=1, probe=lambda h, p: (False, "refused"), ports=(8000, 8080),
                                       is_free=lambda p: p != 8080)


def test_the_report_counts_and_lists_each_problem_on_its_own_line():
    text = preflight.report(["first thing", "second thing"])

    assert text.startswith("The browser tests cannot start: 2 things to fix first.")
    assert "  - first thing\n  - second thing" in text
    assert "1 thing to fix first" in preflight.report(["only"])
