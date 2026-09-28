"""Exercise connection limits against real loopback TCP sockets."""
import io
import json
from queue import Queue
import socket
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from urllib.request import urlopen

from bambuoff.__main__ import Handler, Status, StatusServer
from scripts import bambu_login


class SmallServer(StatusServer):
    max_connections = 2
    idle_timeout = 0.3
    connection_lifetime = 0.9

    def __init__(self):
        self.started = Queue()
        self.finished = Queue()
        super().__init__(("127.0.0.1", 0), Handler)

    def finish_request(self, request, address):
        self.started.put(address)
        super().finish_request(request, address)

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.finished.put(address)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = SmallServer()
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01})
        self.thread.start()
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()

    def connect(self):
        client = socket.create_connection(self.server.server_address, timeout=2)
        self.clients.append(client)
        return client

    def assert_closed(self, client):
        try:
            self.assertEqual(client.recv(1024), b"")
        except ConnectionResetError:
            pass

    def test_status_page_and_health_still_work(self):
        with patch.object(Status, "snapshot", {"mode": "demo"}), \
                patch.object(Status, "updated", time.monotonic()):
            for path in ("/", "/status", "/health"):
                with urlopen(f"http://127.0.0.1:{self.server.server_port}{path}", timeout=2) as response:
                    self.assertEqual(response.status, 200)
                    body = response.read()
                    if path == "/status":
                        self.assertEqual(json.loads(body), {"mode": "demo"})
                self.server.finished.get(timeout=2)

    def test_idle_connection_expires_and_capacity_recovers(self):
        client = self.connect()
        self.server.started.get(timeout=2)
        self.assert_closed(client)
        self.server.finished.get(timeout=2)
        self.test_status_page_and_health_still_work()

    def test_excess_connections_are_closed_without_new_workers(self):
        # Keep the two accepted workers occupied while checking admission.
        self.server.idle_timeout = 5
        self.server.connection_lifetime = 5
        for _ in range(2):
            self.connect()
            self.server.started.get(timeout=2)
        for _ in range(12):
            self.assert_closed(self.connect())
        self.assertTrue(self.server.started.empty())
        for client in self.clients[:2]:
            client.close()
            self.server.finished.get(timeout=2)
        self.test_status_page_and_health_still_work()

    def test_trickled_headers_cannot_extend_absolute_deadline(self):
        client = self.connect()
        self.server.started.get(timeout=2)
        client.sendall(b"GET /status HTTP/1.1\r\nX-Slow: ")
        stopped = threading.Event()

        def trickle():
            while not stopped.wait(0.05):
                try:
                    client.sendall(b"x")
                except OSError:
                    break

        sender = threading.Thread(target=trickle)
        sender.start()
        start = time.monotonic()
        try:
            self.assert_closed(client)
            self.assertLess(time.monotonic() - start, 2)
            self.server.finished.get(timeout=2)
        finally:
            stopped.set()
            sender.join(timeout=2)
        self.test_status_page_and_health_still_work()

    def test_worker_start_failure_releases_capacity(self):
        client, peer = socket.socketpair()
        try:
            with patch("threading.Thread.start", side_effect=RuntimeError("no threads")):
                with self.assertRaises(RuntimeError):
                    self.server.process_request(client, ("127.0.0.1", 0))
            for _ in range(self.server.max_connections):
                self.assertTrue(self.server.slots.acquire(blocking=False))
            for _ in range(self.server.max_connections):
                self.server.slots.release()
        finally:
            client.close()
            peer.close()


class LoginOutputTests(unittest.TestCase):
    def test_failures_do_not_print_exception_details_or_traceback(self):
        secret = "SENSITIVE-test-token"
        for error in (ValueError(secret), OSError(secret),
                      UnicodeDecodeError("utf-8", secret.encode(), 0, 1, secret)):
            with self.subTest(error=type(error).__name__):
                output = io.StringIO()
                with patch.object(bambu_login, "main", side_effect=error), \
                        redirect_stdout(output), redirect_stderr(output):
                    self.assertEqual(bambu_login.cli(), 1)
                self.assertIn("fehlgeschlagen", output.getvalue())
                self.assertNotIn(secret, output.getvalue())
                self.assertNotIn("Traceback", output.getvalue())

    def test_success_and_cancellation_exit_codes(self):
        with patch.object(bambu_login, "main"):
            self.assertEqual(bambu_login.cli(), 0)
        with patch.object(bambu_login, "main", side_effect=KeyboardInterrupt), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(bambu_login.cli(), 130)
