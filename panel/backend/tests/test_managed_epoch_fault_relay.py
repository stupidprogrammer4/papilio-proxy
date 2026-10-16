"""Prove the test relay drops only the first committed rollover response."""

import hashlib
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

from tests.managed_epoch_fault_relay import ManagedRolloverResponseDrop


class ManagedEpochFaultRelayTest(unittest.TestCase):
    def test_committed_rollover_response_can_be_held_until_parent_is_killed(
        self,
    ):
        records = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                request_body = self.rfile.read(length)
                records.append(request_body)
                response_body = b'{"success":true,"data":{"id":17}}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        host = str(upstream.server_address[0])
        port = upstream.server_address[1]
        path = (
            "/v1/nodes/fixture/managed-epochs/"
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/rollover"
        )
        body = b'{"request_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        result = []
        try:
            with ManagedRolloverResponseDrop(
                f"http://{host}:{port}", hold_first_rollover_response=True
            ) as relay:
                client = httpx.Client(timeout=2, trust_env=False)

                def send() -> None:
                    try:
                        result.append(
                            client.post(relay.url + path, content=body)
                        )
                    except httpx.HTTPError:
                        result.append(None)

                request = threading.Thread(target=send)
                request.start()
                self.assertTrue(relay.wait_for_held_rollover(2))
                self.assertEqual(records, [body])
                self.assertEqual(len(relay.rollover_responses()), 1)
                relay.release_held_rollover()
                request.join(timeout=2)
                self.assertFalse(request.is_alive())
                self.assertEqual(result, [None])
                replay = client.post(relay.url + path, content=body)
                client.close()
                self.assertEqual(replay.status_code, 200)
                self.assertEqual(len(records), 2)
                self.assertEqual(records[0], records[1])
                self.assertEqual(len(relay.rollover_responses()), 2)
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=5)

    def test_first_rollover_response_is_dropped_and_exact_replay_is_returned(
        self,
    ):
        records = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                request_body = self.rfile.read(length)
                records.append(
                    (
                        self.path,
                        self.headers.get("X-Papilio-Node-Key"),
                        request_body,
                    )
                )
                response_body = b'{"success":true,"data":{"id":17}}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_body)))
                self.end_headers()
                self.wfile.write(response_body)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        host = str(upstream.server_address[0])
        port = upstream.server_port
        body = b'{"request_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
        path = (
            "/v1/nodes/fixture/managed-epochs/"
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/rollover"
        )
        try:
            with ManagedRolloverResponseDrop(f"http://{host}:{port}") as relay:
                with httpx.Client(timeout=2, trust_env=False) as client:
                    headers = {
                        "Content-Type": "application/json",
                        "X-Papilio-Node-Key": "fixture-node-key",
                    }
                    with self.assertRaises(httpx.HTTPError):
                        client.post(
                            relay.url + path, content=body, headers=headers
                        )
                    replay = client.post(
                        relay.url + path, content=body, headers=headers
                    )
                self.assertEqual(replay.status_code, 200)
                self.assertEqual(
                    replay.content, b'{"success":true,"data":{"id":17}}'
                )
                relay_responses = relay.rollover_responses()
                self.assertEqual(len(relay_responses), 2)
                self.assertEqual(relay_responses[0], relay_responses[1])
                self.assertEqual(
                    relay_responses[0][0], hashlib.sha256(body).hexdigest()
                )
                self.assertEqual(
                    relay.events()[-2:],
                    (
                        ("POST", "rollover", 200),
                        ("POST", "rollover", 200),
                    ),
                )
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0], records[1])
            self.assertEqual(records[0], (path, "fixture-node-key", body))
        finally:
            upstream.shutdown()
            upstream.server_close()
            thread.join(timeout=5)
