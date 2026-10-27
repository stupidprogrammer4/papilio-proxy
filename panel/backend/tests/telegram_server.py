"""Controlled external Telegram API double; internal application paths stay real."""

import json
import threading
from collections.abc import Callable
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class TelegramServer:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.pending: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.webhook = ""
        self.replies: dict[str, tuple[int, object]] = {}
        self.scripted_replies: dict[str, list[tuple[int, object]]] = {}
        self.hold_next = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.next_error_status: int | None = None
        self.messages: list[tuple[int, dict[str, Any]]] = []
        self.files: dict[str, bytes] = {}
        self.file_calls: list[str] = []
        self.file_statuses: list[int] = []
        self.download_observer: Callable[[], None] | None = None

    def push(
        self,
        identifier: int,
        text: str,
        *,
        chat_id: int = 456789,
        sender_id: int | None = None,
        kind: str = "private",
    ) -> None:
        update = {
            "update_id": identifier,
            "message": {
                "message_id": identifier,
                "chat": {"id": chat_id, "type": kind},
                "from": {"id": chat_id if sender_id is None else sender_id},
                "text": text,
            },
        }
        with self.lock:
            self.pending.append(update)

    def push_callback(self, identifier: int, data: str, *, chat_id: int, bot_id: int) -> None:
        with self.lock:
            self.pending.append(
                {
                    "update_id": identifier,
                    "callback_query": {
                        "id": f"shop-callback-{identifier}",
                        "from": {"id": chat_id},
                        "data": data,
                        "message": {
                            "message_id": 100,
                            "from": {"id": bot_id, "is_bot": True},
                            "chat": {"id": chat_id, "type": "private"},
                        },
                    },
                }
            )

    def push_photo(
        self,
        identifier: int,
        file_id: str,
        *,
        chat_id: int,
        reply_to_message_id: int | None = None,
        bot_id: int | None = None,
        caption: str = "",
    ) -> None:
        message: dict[str, Any] = {
            "message_id": identifier,
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id},
            "photo": [{"file_id": file_id}],
            "caption": caption,
        }
        if reply_to_message_id is not None:
            assert bot_id is not None
            message["reply_to_message"] = {
                "message_id": reply_to_message_id,
                "chat": {"id": chat_id, "type": "private"},
                "from": {"id": bot_id, "is_bot": True},
            }
        with self.lock:
            self.pending.append({"update_id": identifier, "message": message})

    def hold(self) -> None:
        self.entered.clear()
        self.release.clear()
        self.hold_next = True

    def respond(
        self, method: str, parameters: dict[str, Any], identity_id: int
    ) -> tuple[int, object]:
        with self.lock:
            self.calls.append((method, parameters))
            scripted = self.scripted_replies.get(method)
            if scripted:
                return scripted.pop(0)
            if method in self.replies:
                return self.replies[method]
            if self.next_error_status is not None:
                status = self.next_error_status
                self.next_error_status = None
                return status, {"ok": False, "parameters": {"retry_after": 1}}
            hold = self.hold_next and method == "getUpdates"
            if hold:
                self.hold_next = False
        if hold:
            self.entered.set()
            assert self.release.wait(timeout=10)
        result: object = None
        if method == "fixturePush":
            self.push(int(parameters["update_id"]), str(parameters["text"]))
            result = True
        if method == "getMe":
            result = {
                "id": identity_id,
                "is_bot": True,
                "username": f"papilio_test_{identity_id}_bot",
            }
        if method == "getWebhookInfo":
            result = {
                "url": self.webhook,
                "pending_update_count": 0,
                "has_custom_certificate": False,
            }
        if method == "getUpdates":
            with self.lock:
                result = [
                    item for item in self.pending if item["update_id"] >= parameters["offset"]
                ][: parameters["limit"]]
        if method == "sendMessage":
            with self.lock:
                message_id = len(self.messages) + 100
                self.messages.append((message_id, parameters.copy()))
            result = {
                "message_id": message_id,
                "chat": {"id": parameters["chat_id"], "type": "private"},
                "text": parameters["text"],
            }
        if method == "sendPhoto":
            with self.lock:
                message_id = len(self.messages) + 100
                self.messages.append(
                    (
                        message_id,
                        {
                            "chat_id": parameters["chat_id"],
                            "text": parameters["caption"],
                            "reply_markup": parameters.get("reply_markup"),
                        },
                    )
                )
            result = {
                "message_id": message_id,
                "chat": {"id": parameters["chat_id"], "type": "private"},
                "photo": [{"file_id": "controlled-photo"}],
                "caption": parameters["caption"],
            }
        if method == "answerCallbackQuery":
            result = True
        if method == "getFile":
            path = f"photos/{parameters['file_id']}.jpg"
            result = {
                "file_id": parameters["file_id"],
                "file_path": path,
                "file_size": len(self.files.get(path, b"")),
            }
        return 200, {"ok": True, "result": result}

    @contextmanager
    def running(self):
        state = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                from urllib.parse import unquote

                path = unquote(self.path.removeprefix("/file/bot").split("/", maxsplit=1)[1])
                if state.download_observer is not None:
                    state.download_observer()
                with state.lock:
                    state.file_calls.append(path)
                    content = state.files.get(path)
                    status = (
                        state.file_statuses.pop(0)
                        if state.file_statuses
                        else (200 if content is not None else 404)
                    )
                if status == 0:
                    self.close_connection = True
                    return
                self.send_response(status)
                self.send_header("Content-Type", "application/octet-stream")
                self.end_headers()
                self.wfile.write(content or b"")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                parameters = json.loads(self.rfile.read(length))
                credential, method = self.path.removeprefix("/bot").split("/", maxsplit=1)
                status, result = state.respond(method, parameters, int(credential.split(":")[0]))
                content = json.dumps(result).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}"
        finally:
            self.release.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
