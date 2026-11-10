"""The egress guard really refuses non-local connections (M7, #111; BR-37). No database, no network."""

from __future__ import annotations

import socket
import threading
import unittest
import urllib.error
import urllib.request

import pytest

from tests import egress_guard
from tests.egress_guard import EgressBlocked, check_local_database, is_local


@pytest.mark.unit
class WhatIsLocal(unittest.TestCase):
    def test_loopback_names_addresses_and_socket_directories_are_local(self):
        for host in ("localhost", "127.0.0.1", "127.1.2.3", "::1", "[::1]", "/var/run/postgresql", None, ""):
            self.assertTrue(is_local(host), host)

    def test_everything_else_is_not(self):
        for host in ("example.com", "93.184.216.34", "10.0.0.5", "192.168.1.1", "0.0.0.0", "db.internal", "2001:db8::1"):
            self.assertFalse(is_local(host), host)

    def test_a_remote_database_host_is_refused_up_front(self):
        check_local_database("localhost")
        check_local_database("/var/run/postgresql")
        with self.assertRaises(EgressBlocked):
            check_local_database("db.example.com")


@pytest.mark.unit
class GuardBehaviour(unittest.TestCase):
    def setUp(self):
        self._active = bool(egress_guard._originals)   # already installed by `pytest --block-egress`
        egress_guard.uninstall()
        egress_guard.attempts.clear()
        egress_guard.install()

    def tearDown(self):
        egress_guard.uninstall()
        if self._active:
            egress_guard.install()
        else:
            egress_guard.attempts.clear()

    def test_connecting_to_a_public_address_is_blocked_before_any_packet_is_sent(self):
        with self.assertRaises(EgressBlocked):
            socket.create_connection(("93.184.216.34", 80), timeout=1)   # resolves first, and is stopped there
        self.assertEqual(egress_guard.attempts, ["resolve 93.184.216.34"])

    def test_a_direct_connect_is_blocked_too(self):
        sock = socket.socket()
        try:
            with self.assertRaises(EgressBlocked):
                sock.connect(("93.184.216.34", 80))
            self.assertEqual(sock.connect_ex.__name__, "connect_ex")
            with self.assertRaises(EgressBlocked):
                sock.connect_ex(("10.255.255.1", 443))
        finally:
            sock.close()
        self.assertEqual(egress_guard.attempts, ["connect to 93.184.216.34:80", "connect to 10.255.255.1:443"])

    def test_resolving_a_remote_name_is_blocked(self):
        with self.assertRaises(EgressBlocked):
            socket.getaddrinfo("example.com", 443)
        self.assertEqual(egress_guard.attempts, ["resolve example.com"])

    def test_higher_level_clients_are_caught_too(self):
        with self.assertRaises((EgressBlocked, urllib.error.URLError)):
            urllib.request.urlopen("http://example.com/", timeout=1)  # nosec B310 - proving it is blocked
        self.assertTrue(egress_guard.attempts)

    def test_loopback_still_works(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        threading.Thread(target=lambda: server.accept()[0].close(), daemon=True).start()
        with socket.create_connection(("127.0.0.1", server.getsockname()[1]), timeout=2):
            pass
        server.close()
        self.assertEqual(egress_guard.attempts, [])

    def test_unix_sockets_are_not_network_egress(self):
        a, b = socket.socketpair()
        a.close()
        b.close()
        self.assertEqual(egress_guard.attempts, [])

    def test_uninstall_restores_the_originals(self):
        egress_guard.uninstall()
        self.assertIs(socket.getaddrinfo, getattr(socket, "getaddrinfo"))
        self.assertFalse(egress_guard._originals)
        egress_guard.install()
