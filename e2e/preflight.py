"""What the browser tests need, checked together and first (before the slow React build and the servers).

Each check returns one message saying what is missing and how to fix it, or None. conftest.py runs them
all at the start of the session and stops with every problem listed, instead of failing one at a time with
whatever error the first missing piece happens to raise (a Playwright "Executable doesn't exist" trace,
a connection error from the database pool, a server that never comes up).

No Playwright import at module level, so tests/unit can load this file where Playwright is not installed.
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

REMEDY_PORT = "stop whatever listens on it (or the previous run's servers) and rerun"


def check_playwright() -> str | None:
    """Is Playwright installed? Asked of the package metadata: the package has no __version__ attribute."""
    try:
        importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        return "Playwright is not installed: pip install playwright && playwright install chromium"
    return None


def check_browser(env: Mapping[str, str]) -> str | None:
    """An E2E_CHROMIUM override must point at a real file. Without one, Playwright's own browser is used,
    and a missing one is reported by conftest's browser fixture, which is the only place that can tell."""
    override = env.get("E2E_CHROMIUM")
    if override and not Path(override).exists():
        return (
            f"E2E_CHROMIUM points at {override}, which does not exist. Unset it to use Playwright's own "
            "Chromium (`playwright install chromium`), or point it at an installed Chrome or Chromium"
        )
    return None


def check_postgres(host: str, port: str | int, probe: Callable[[str, str], tuple[bool, str]]) -> str | None:
    """Is PostgreSQL accepting connections where the tests will look for it? `probe` is
    scripts/pg_login.py's server_available, which sends no credentials."""
    up, why = probe(host, str(port))
    if up:
        return None
    return (
        f"PostgreSQL is not accepting connections at {host}:{port} ({why}). Start it, or set PGHOST and "
        "PGPORT to where it is, and deploy the dev database (bash build/deploy_all.sh dev)"
    )


def check_ports(ports: Iterable[int], is_free: Callable[[int], bool]) -> list[str]:
    return [f"port {p} is in use: {REMEDY_PORT}" for p in ports if not is_free(p)]


def check_node_modules(root: Path) -> str | None:
    if (root / "csv-table-hub-main" / "node_modules").exists():
        return None
    return "the React app's dependencies are missing: run `npm ci` in csv-table-hub-main"


def check_streamlit() -> str | None:
    if importlib.util.find_spec("streamlit") is not None:
        return None
    return "Streamlit is not installed: pip install -r streamlit_app/requirements.txt"


def problems(
    *,
    root: Path,
    env: Mapping[str, str],
    pg_host: str,
    pg_port: str | int,
    probe: Callable[[str, str], tuple[bool, str]],
    ports: Iterable[int],
    is_free: Callable[[int], bool],
) -> list[str]:
    """Every problem found, in the order a person would fix them. Empty when the tests can start."""
    found = [
        check_playwright(),
        check_browser(env),
        check_streamlit(),
        check_node_modules(root),
        check_postgres(pg_host, pg_port, probe),
    ]
    return [m for m in found if m] + check_ports(ports, is_free)


def report(found: list[str]) -> str:
    n = len(found)
    lines = "\n".join(f"  - {m}" for m in found)
    return f"The browser tests cannot start: {n} thing{'s' if n != 1 else ''} to fix first.\n{lines}"
