"""Refuse in-process network connections to anything but this machine (M7, #111; BR-37, decision 7).

``install()`` replaces ``socket.socket.connect``, ``connect_ex`` and ``socket.getaddrinfo`` so a name
or address that isn't loopback (or a Unix socket) raises ``EgressBlocked`` and is recorded in
``attempts``. Used by ``pytest --block-egress`` (see conftest.py) and ``make test-egress-blocked``.

Limits, by design: it covers Python code in this process. libpq (psycopg2) connects below Python, so the
database host is checked up front with ``check_local_database``; child processes (psql, the shell
loaders) are not covered. Blocking at the network layer is the stronger check, for an on-premises or
offline rehearsal (docs/SOVEREIGNTY.md).
"""

from __future__ import annotations

import ipaddress
import socket

attempts: list[str] = []
_originals: dict = {}


class EgressBlocked(OSError):
    """A connection or lookup to somewhere other than this machine."""


def is_local(host) -> bool:
    if host in (None, "", b""):
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    host = host.strip("[]")
    if host == "localhost" or host.startswith("/"):   # a Unix socket directory, as libpq takes it
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_local_database(host: str) -> None:
    """libpq's connection can't be intercepted from Python, so refuse a remote database host outright."""
    if not is_local(host):
        raise EgressBlocked(f"The database host {host!r} is not on this machine; an egress-blocked run needs a local one.")


def _blocked(what: str) -> EgressBlocked:
    attempts.append(what)
    return EgressBlocked(f"Blocked outbound network access: {what}")


def install() -> None:
    if _originals:
        return
    _originals.update(connect=socket.socket.connect, connect_ex=socket.socket.connect_ex,
                      getaddrinfo=socket.getaddrinfo)

    def check_address(sock, address, what):
        if sock.family == socket.AF_UNIX or not isinstance(address, tuple) or is_local(address[0]):
            return
        raise _blocked(f"{what} {address[0]}:{address[1] if len(address) > 1 else ''}")

    def connect(self, address):
        check_address(self, address, "connect to")
        return _originals["connect"](self, address)

    def connect_ex(self, address):
        check_address(self, address, "connect to")
        return _originals["connect_ex"](self, address)

    def getaddrinfo(host, *args, **kwargs):
        if not is_local(host):
            raise _blocked(f"resolve {host}")
        return _originals["getaddrinfo"](host, *args, **kwargs)

    socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo


def uninstall() -> None:
    if _originals:
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = (
            _originals["connect"], _originals["connect_ex"], _originals["getaddrinfo"])
        _originals.clear()
