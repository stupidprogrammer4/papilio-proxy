from __future__ import annotations

import asyncio
from io import BytesIO
from urllib.parse import urlsplit

import qrcode
from qrcode.constants import ERROR_CORRECT_M


class QrRenderer:
    """Render private connection links in memory, off the event loop.

    Share one instance per application event loop. Cancelling a request cannot
    cancel its running thread, so its slot remains occupied until work finishes.
    """

    MAX_PAYLOAD_BYTES = 2000

    def __init__(self, *, max_concurrency: int = 2) -> None:
        if isinstance(max_concurrency, bool) or not isinstance(max_concurrency, int):
            raise TypeError("QR concurrency must be a positive integer")
        if max_concurrency < 1:
            raise ValueError("QR concurrency must be a positive integer")
        self._slots = asyncio.Semaphore(max_concurrency)
        self._workers: set[asyncio.Task[bytes]] = set()

    async def render(self, value: str) -> bytes:
        self._validate(value)
        await self._slots.acquire()
        worker = asyncio.create_task(asyncio.to_thread(self._render_png, value))
        self._workers.add(worker)
        worker.add_done_callback(self._worker_finished)
        return await asyncio.shield(worker)

    def _worker_finished(self, worker: asyncio.Task[bytes]) -> None:
        self._workers.discard(worker)
        self._slots.release()
        if not worker.cancelled():
            worker.exception()

    @classmethod
    def _validate(cls, value: str) -> None:
        if not isinstance(value, str) or not value or len(value) > cls.MAX_PAYLOAD_BYTES:
            raise ValueError("Invalid QR link")
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError("Invalid QR link")
        try:
            if len(value.encode("utf-8")) > cls.MAX_PAYLOAD_BYTES:
                raise ValueError("Invalid QR link")
            parsed = urlsplit(value)
            if parsed.scheme not in {"https", "vless", "vmess"} or not parsed.netloc:
                raise ValueError("Invalid QR link")
            if parsed.scheme == "https" and (
                not parsed.hostname or parsed.username is not None or parsed.password is not None
            ):
                raise ValueError("Invalid QR link")
        except (ValueError, UnicodeError):
            raise ValueError("Invalid QR link") from None

    @staticmethod
    def _render_png(value: str) -> bytes:
        qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=4)
        qr.add_data(value.encode("utf-8"))
        qr.make(fit=True)
        with BytesIO() as output:
            qr.make_image(fill_color="black", back_color="white").save(output)
            return output.getvalue()
