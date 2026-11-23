"""#310 (OIT-029, BR-37): the network block holds for child processes and for libpq, not just for Python sockets.

``tests/egress_guard.py`` patches ``socket`` in this process only. These tests are the negative control for the stronger
check: the CI job that runs ``pytest tests/system --block-egress`` first blocks the test user's network at the firewall
(``scripts/egress_firewall.sh``), then runs THIS file as that user to prove the block works, with deliberate outbound
attempts from a child process and from libpq (which connects below Python). Nothing else in the suite is allowed to try;
the job counts the refused packets and fails if the count is not zero.

They only make sense behind that firewall, so ``tests/conftest.py`` leaves them out of every other run (marker
``egress_network``, set ``EGRESS_NETWORK_BLOCKED=1`` to include them). On an open network they would connect.
"""
from __future__ import annotations

import errno
import subprocess
import sys
import time

import pytest

from api.config import settings

pytestmark = pytest.mark.egress_network

OUTSIDE = "93.184.216.34"   # a public address; the firewall must refuse before anything is sent
REFUSED = {errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPERM, errno.EACCES}

SOCKET_CHILD = f"""
import socket, sys, time
started = time.monotonic()
try:
    socket.create_connection(({OUTSIDE!r}, 80), timeout=8).close()
except OSError as exc:
    print("blocked", exc.errno, f"{{time.monotonic() - started:.2f}}")
    sys.exit(0)
print("CONNECTED")
sys.exit(7)
"""

LIBPQ_CHILD = f"""
import sys, time
import psycopg2
started = time.monotonic()
try:
    psycopg2.connect(host={OUTSIDE!r}, port=5432, user="x", password="x", dbname="x", connect_timeout=8).close()
except psycopg2.OperationalError as exc:
    print("blocked", f"{{time.monotonic() - started:.2f}}", str(exc).strip().splitlines()[0])
    sys.exit(0)
print("CONNECTED")
sys.exit(7)
"""

LOCAL_CHILD = f"""
import socket, sys
try:
    socket.create_connection(({settings.PG_HOST!r}, {int(settings.PG_PORT)}), timeout=5).close()
except OSError as exc:
    print("unreachable", exc)
    sys.exit(7)
print("reachable")
"""


def child(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)


def test_a_child_python_process_cannot_reach_a_public_address():
    done = child(SOCKET_CHILD)
    assert done.returncode == 0 and done.stdout.startswith("blocked"), (done.stdout, done.stderr)
    _, code, seconds = done.stdout.split()
    assert int(code) in REFUSED, f"expected the firewall's refusal, got errno {code}: {done.stdout}"
    assert float(seconds) < 3, f"it was refused only after {seconds}s, which looks like a timeout, not the firewall"


def test_libpq_in_a_child_process_cannot_reach_a_remote_database():
    """libpq connects below Python, so the in-process guard cannot see it; only the firewall stops it."""
    done = child(LIBPQ_CHILD)
    assert done.returncode == 0 and done.stdout.startswith("blocked"), (done.stdout, done.stderr)
    assert float(done.stdout.split()[1]) < 3, f"refused only after a wait, which looks like a timeout: {done.stdout}"


def test_this_machine_is_still_reachable_from_a_child_process():
    """Without this, the two tests above would pass on a machine with no network at all."""
    done = child(LOCAL_CHILD)
    assert done.returncode == 0 and done.stdout.strip() == "reachable", (done.stdout, done.stderr)


def test_the_refusal_is_immediate_not_a_wait():
    started = time.monotonic()
    done = child(SOCKET_CHILD)
    assert done.returncode == 0
    assert time.monotonic() - started < 10
