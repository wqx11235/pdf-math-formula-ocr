"""Jev 客户端：成功、5xx 重试、4xx 不重试、返回体异常。"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

from pmocr.errors import JevError
from pmocr.jev import JevClient
from tests.helpers import make_tmp


class _State:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server 约定
        state = self.server.state
        length = int(self.headers.get("Content-Length") or 0)
        state.calls.append(json.loads(self.rfile.read(length) or b"{}"))
        index = min(len(state.calls) - 1, len(state.responses) - 1)
        status, payload = state.responses[index]
        body = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def _ok(prob: float = 0.87) -> bytes:
    return json.dumps({"answers": {"consistency": {"probabilities": {"1": prob}}}}).encode()


class JevClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = make_tmp()
        self.region = self.tmp / "region.png"
        self.candidate = self.tmp / "candidate.png"
        Image.new("RGB", (40, 20), "white").save(self.region)
        Image.new("RGB", (40, 20), "black").save(self.candidate)
        self.servers: list[ThreadingHTTPServer] = []
        self.sleeps: list[float] = []

    def tearDown(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()

    def _client(self, responses, retries: int = 2) -> JevClient:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.state = _State(responses)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append(server)
        host, port = server.server_address[:2]
        return JevClient(
            url="http://%s:%d/v1/systemone" % (host, port),
            model="jev",
            retries=retries,
            backoff=0.01,
            sleep=self.sleeps.append,
        )

    def test_returns_probability(self) -> None:
        client = self._client([(200, _ok(0.87))])
        self.assertAlmostEqual(client.score(self.region, "x^2", self.candidate), 0.87)

    def test_payload_shape(self) -> None:
        client = self._client([(200, _ok(0.5))])
        client.score(self.region, "x^2", self.candidate)
        body = self.servers[0].state.calls[0]
        self.assertEqual(body["model"], "jev")
        self.assertEqual(body["state"], "x^2")
        self.assertEqual(len(body["images"]), 2)
        self.assertIn("consistency", body["questions"])

    def test_retries_on_500(self) -> None:
        client = self._client([(500, b'{"error":"Internal Server Error"}'), (200, _ok(0.4))])
        self.assertAlmostEqual(client.score(self.region, "x", self.candidate), 0.4)
        self.assertEqual(len(self.servers[0].state.calls), 2)
        self.assertEqual(len(self.sleeps), 1)

    def test_does_not_retry_on_400(self) -> None:
        client = self._client([(400, b'{"error":"bad request"}'), (200, _ok(0.9))])
        with self.assertRaises(JevError):
            client.score(self.region, "x", self.candidate)
        self.assertEqual(len(self.servers[0].state.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_retries_on_malformed_body(self) -> None:
        client = self._client([(200, b"{}"), (200, b"{}"), (200, b"{}")], retries=2)
        with self.assertRaises(JevError):
            client.score(self.region, "x", self.candidate)
        self.assertEqual(len(self.servers[0].state.calls), 3)

    def test_exhausted_retries_raise(self) -> None:
        client = self._client([(503, b"{}")], retries=2)
        with self.assertRaises(JevError) as ctx:
            client.score(self.region, "x", self.candidate)
        self.assertIn("重试", str(ctx.exception))

    def test_missing_image_raises(self) -> None:
        client = self._client([(200, _ok())])
        with self.assertRaises(JevError):
            client.score(self.tmp / "nope.png", "x", self.candidate)

    def test_from_config_builds_endpoint(self) -> None:
        from pmocr.config import Config

        cfg = Config.load(None, overrides={"jev_url": "http://127.0.0.1:18499/"}, environ={})
        client = JevClient.from_config(cfg)
        self.assertEqual(client.url, "http://127.0.0.1:18499/v1/systemone")


if __name__ == "__main__":
    unittest.main()
