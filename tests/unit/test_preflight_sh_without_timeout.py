"""#309 (OIT-027, BR-38 portability): preflight.sh's port check must work where `timeout` does not exist.

`timeout` is GNU coreutils. Stock macOS has none (Homebrew installs it as `gtimeout`), so the PostgreSQL port check in
preflight.sh, which ran ``timeout 3 bash -c '</dev/tcp/HOST/PORT'``, failed to start and reported "PG not listening"
for a server that was up. Asserted here by running the real script with a PATH that has no ``timeout``:

  * an open port is reported as reachable (PASS) and a closed one is not;
  * the same with only ``gtimeout`` on the PATH (macOS with coreutils);
  * ``with_timeout``, the helper the check now uses, runs a command with a time limit using ``timeout``, ``gtimeout``
    or, when neither exists, plain bash; it keeps the command's exit status, stops a hung command on time, and does not
    leave anything behind that makes a caller wait.

`tooling` only: these run bash, and the Windows job's `bash` is WSL's, with no distribution installed.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest

pytestmark = pytest.mark.tooling

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "preflight.sh"
# What preflight.sh and with_timeout need from the PATH, besides bash itself.
TOOLS = ("bash", "sh", "sleep", "git", "cat", "sed", "grep", "tr", "uname", "date", "env", "true", "false")


def path_dir(tmp_path: Path, *, gtimeout: bool = False, timeout: bool = False) -> str:
    """A PATH directory holding only ``TOOLS``, plus ``timeout`` and/or ``gtimeout`` if asked: a stock macOS."""
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    for name in TOOLS:
        found = shutil.which(name)
        if found and not (shim / name).exists():
            (shim / name).symlink_to(found)
    real = shutil.which("timeout")
    if real and timeout and not (shim / "timeout").exists():
        (shim / "timeout").symlink_to(real)
    if real and gtimeout and not (shim / "gtimeout").exists():
        (shim / "gtimeout").symlink_to(real)
    return str(shim)


def run_preflight(path: str, host: str, port: int) -> str:
    env = {"PATH": path, "HOME": str(Path.home()), "PGHOST": host, "PGPORT": str(port)}
    done = subprocess.run([shutil.which("bash"), str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=120)
    return done.stdout


def port_line(output: str, port: int) -> str:
    match = re.search(rf"^.*port {port} reachable on [^\]]+\] \.\.\. (\w+).*$", output, re.MULTILINE)
    assert match, f"no port line in the output:\n{output}"
    return match.group(1)


@pytest.fixture
def listening_port():
    with closing(socket.socket()) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(5)
        yield server.getsockname()[1]


@pytest.fixture
def closed_port():
    with closing(socket.socket()) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]   # closed again as soon as the block ends


# -- the real script, on a PATH like stock macOS ---------------------------------------------------------------------

def test_an_open_port_is_reachable_with_no_timeout_command(tmp_path, listening_port):
    assert port_line(run_preflight(path_dir(tmp_path), "127.0.0.1", listening_port), listening_port) == "PASS"


def test_a_closed_port_is_still_reported_unreachable_with_no_timeout_command(tmp_path, closed_port):
    assert port_line(run_preflight(path_dir(tmp_path), "127.0.0.1", closed_port), closed_port) == "WARN"


@pytest.mark.skipif(not shutil.which("timeout"), reason="needs GNU timeout to stand in for gtimeout")
def test_an_open_port_is_reachable_with_only_gtimeout(tmp_path, listening_port):
    path = path_dir(tmp_path, gtimeout=True)
    assert port_line(run_preflight(path, "127.0.0.1", listening_port), listening_port) == "PASS"


@pytest.mark.skipif(not shutil.which("timeout"), reason="needs GNU timeout")
def test_an_open_port_is_still_reachable_with_the_gnu_timeout(tmp_path, listening_port):
    path = path_dir(tmp_path, timeout=True)
    assert port_line(run_preflight(path, "127.0.0.1", listening_port), listening_port) == "PASS"


# -- with_timeout itself ---------------------------------------------------------------------------------------------

def helper() -> str:
    text = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"^with_timeout\(\) \{.*?^\}\n", text, re.DOTALL | re.MULTILINE)
    assert match, "preflight.sh must define with_timeout()"
    return match.group(0)


def with_timeout(path: str, *args: str) -> tuple[int, float]:
    started = time.monotonic()
    done = subprocess.run([shutil.which("bash"), "-c", helper() + '\nwith_timeout "$@"', "_", *args],
                          env={"PATH": path}, capture_output=True, text=True, timeout=60)
    return done.returncode, time.monotonic() - started


@pytest.mark.parametrize("variant", ["none", "gtimeout", "timeout"])
def test_it_keeps_the_exit_status_of_the_command(tmp_path, variant):
    if variant != "none" and not shutil.which("timeout"):
        pytest.skip("needs GNU timeout")
    path = path_dir(tmp_path, gtimeout=variant == "gtimeout", timeout=variant == "timeout")
    assert with_timeout(path, "3", "bash", "-c", "exit 0")[0] == 0
    assert with_timeout(path, "3", "bash", "-c", "exit 7")[0] == 7


@pytest.mark.parametrize("variant", ["none", "gtimeout", "timeout"])
def test_it_stops_a_hung_command_on_time(tmp_path, variant):
    if variant != "none" and not shutil.which("timeout"):
        pytest.skip("needs GNU timeout")
    path = path_dir(tmp_path, gtimeout=variant == "gtimeout", timeout=variant == "timeout")
    status, elapsed = with_timeout(path, "1", "sleep", "20")
    assert status != 0, "a command that hit the limit is a failure"
    assert 0.8 <= elapsed < 6, f"stopped after {elapsed:.1f}s, not about 1s"


def test_it_does_not_make_a_quick_command_wait_for_the_limit(tmp_path):
    status, elapsed = with_timeout(path_dir(tmp_path), "5", "true")
    assert status == 0 and elapsed < 2.5, f"a command that finished at once took {elapsed:.1f}s"
