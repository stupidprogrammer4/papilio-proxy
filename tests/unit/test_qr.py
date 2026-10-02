from __future__ import annotations

import asyncio
import base64
import importlib
import importlib.util
import json
import threading
from io import BytesIO
from typing import cast
from unittest import IsolatedAsyncioTestCase, TestCase, skipUnless
from unittest.mock import patch

from PIL import Image

from papilio_proxy.modules.network.subscriptions.infra.qr import QrRenderer


class QrRendererTests(IsolatedAsyncioTestCase):
    @skipUnless(importlib.util.find_spec("zxingcpp"), "Optional QR decoder is not installed")
    async def test_independent_decoder_roundtrips_connection_payloads(self) -> None:
        decoder = importlib.import_module("zxingcpp")
        renderer = QrRenderer()
        vmess = {
            "v": "2",
            "ps": "آزمایش Papilio",
            "add": "node.example.test",
            "port": "443",
            "id": "00000000-0000-0000-0000-000000000001",
            "aid": "0",
            "scy": "auto",
            "net": "ws",
            "type": "none",
            "host": "node.example.test",
            "path": "/connect",
            "tls": "tls",
            "sni": "node.example.test",
        }
        payload = json.dumps(vmess, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        links = (
            "https://sub.example.test/sub/dummy-test-token_0123456789?format=base64",
            "vmess://" + base64.b64encode(payload).decode("ascii"),
            (
                "vless://00000000-0000-0000-0000-000000000001@node.example.test:443"
                "?security=reality&type=tcp#Papilio"
            ),
        )
        for link in links:
            with self.subTest(scheme=link.split(":", 1)[0]):
                png = await renderer.render(link)
                with Image.open(BytesIO(png)) as picture:
                    decoded = decoder.read_barcode(picture.convert("RGB"))
                self.assertIsNotNone(decoded)
                self.assertEqual(decoded.bytes, link.encode("utf-8"))

    async def test_supported_links_produce_deterministic_png(self) -> None:
        renderer = QrRenderer()
        links = (
            "https://sub.example.test/sub/test-token",
            "vless://00000000-0000-0000-0000-000000000001@example.test:443#test",
            "vmess://eyJ2IjoiMiIsInBzIjoidGVzdCJ9",
        )
        for link in links:
            with self.subTest(scheme=link.split(":", 1)[0]):
                png = await renderer.render(link)
                self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
                self.assertEqual(png, await renderer.render(link))
                with Image.open(BytesIO(png)) as picture:
                    self.assertEqual(picture.format, "PNG")
                    self.assertEqual(picture.width, picture.height)
                    self.assertGreaterEqual(picture.width, 232)
                    self.assertLessEqual(picture.width, 1480)

    async def test_invalid_links_do_not_start_workers_or_expose_input(self) -> None:
        renderer = QrRenderer()
        links = (
            "",
            "http://example.test/private",
            "file:///tmp/private",
            "vmess://",
            "https:///private",
            "https://user:secret@example.test/private",
            "https://example.test/private\n",
            "https://[invalid/private",
            "https://example.test/" + "x" * 2000,
            "https://example.test/" + "ی" * 1100,
            "https://example.test/\ud800",
        )
        with patch.object(renderer, "_render_png") as worker:
            for link in links:
                with (
                    self.subTest(length=len(link)),
                    self.assertRaisesRegex(ValueError, "^Invalid QR link$"),
                ):
                    await renderer.render(link)
            worker.assert_not_called()

    async def test_loop_keeps_running_during_render(self) -> None:
        renderer = QrRenderer()
        started = threading.Event()
        release = threading.Event()
        ticks = 0

        def blocking_render(value: str) -> bytes:
            started.set()
            if not release.wait(timeout=2):
                raise AssertionError("Event loop failed to run heartbeat during render")
            return b"png"

        async def heartbeat() -> None:
            nonlocal ticks
            while not started.is_set():
                await asyncio.sleep(0.001)
            for _ in range(5):
                ticks += 1
                await asyncio.sleep(0.001)
            release.set()

        with patch.object(renderer, "_render_png", side_effect=blocking_render):
            try:
                await asyncio.wait_for(
                    asyncio.gather(renderer.render("https://example.test/sub"), heartbeat()),
                    timeout=3,
                )
            finally:
                release.set()
        self.assertEqual(ticks, 5)

    async def test_cancelled_request_holds_slot_until_worker_finishes(self) -> None:
        renderer = QrRenderer(max_concurrency=1)
        started = threading.Event()
        release = threading.Event()
        calls: list[int] = []

        def blocking_render(value: str) -> bytes:
            calls.append(len(calls) + 1)
            started.set()
            release.wait(timeout=3)
            return b"png"

        with patch.object(renderer, "_render_png", side_effect=blocking_render):
            first = asyncio.create_task(renderer.render("https://example.test/first"))
            second = None
            try:
                async with asyncio.timeout(2):
                    while not started.is_set():
                        await asyncio.sleep(0.001)
                first.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await first
                second = asyncio.create_task(renderer.render("https://example.test/second"))
                await asyncio.sleep(0.03)
                self.assertEqual(calls, [1])
                release.set()
                self.assertEqual(await asyncio.wait_for(second, timeout=2), b"png")
                self.assertEqual(calls, [1, 2])
            finally:
                release.set()
                await asyncio.gather(first, *([second] if second else []), return_exceptions=True)

    async def test_worker_failure_releases_slot(self) -> None:
        renderer = QrRenderer(max_concurrency=1)
        with patch.object(renderer, "_render_png", side_effect=[RuntimeError("failed"), b"png"]):
            with self.assertRaises(RuntimeError):
                await renderer.render("https://example.test/sub")
            self.assertEqual(
                await asyncio.wait_for(renderer.render("https://example.test/sub"), timeout=1),
                b"png",
            )


class QrRendererConfigurationTests(TestCase):
    def test_invalid_concurrency(self) -> None:
        for concurrency, error in (
            (0, ValueError),
            (-1, ValueError),
            (True, TypeError),
            (1.5, TypeError),
        ):
            with self.subTest(concurrency=concurrency), self.assertRaises(error):
                QrRenderer(max_concurrency=cast(int, concurrency))
