"""Native retained-event scopes and real HTTP Telegram reply/file adaptation."""

from uuid import UUID, uuid4

import pytest
from telegram_server import TelegramServer
from test_bots import bot_input
from test_nodes import owner_client

from papilio_panel.modules.bots.domain import BotReplyRequest, TelegramButton, TelegramReply
from papilio_panel.modules.bots.models import TelegramInbox
from papilio_panel.modules.bots.providers import conversations, polling
from papilio_panel.shared.errors import Conflict, Missing

pytestmark = pytest.mark.django_db(transaction=True)


def connected_event(
    server: TelegramServer, address: str, *, kind: str = "private", sender_id: int = 987654
) -> tuple[int, UUID, int]:
    owner = owner_client()
    result = owner.post(
        "/api/v1/bots", bot_input() | {"runtime": {"api_base_url": address}}, format="json"
    )
    assert result.status_code == 202
    bot_id = UUID(result.json()["id"])
    server.push(1, "hello", chat_id=987654, sender_id=sender_id, kind=kind)
    polling.poll(bot_id)
    row = TelegramInbox.objects.get(bot_id=bot_id, update_id=1)
    event = conversations.event(row.pk)
    return row.pk, bot_id, event.bot.owner_id


def test_native_reply_uses_verified_private_event_and_redacts_transport_credentials() -> None:
    server = TelegramServer()
    with server.running() as address:
        event_id, bot_id, owner_id = connected_event(server, address)
        reply = TelegramReply(
            "A controlled private reply", (TelegramButton("Products", "catalogue:1"),)
        )
        result = conversations.reply(BotReplyRequest(event_id, bot_id, owner_id, reply))
        assert result.message_id is not None and result.error_code is None
        sent = [values for method, values in server.calls if method == "sendMessage"]
        assert len(sent) == 1
        assert sent[0]["chat_id"] == 987654
        assert sent[0]["reply_markup"]["inline_keyboard"] == [
            [{"text": "Products", "callback_data": "catalogue:1"}]
        ]
        assert "token" not in repr(result)
        with pytest.raises(Missing):
            conversations.reply(BotReplyRequest(event_id, uuid4(), owner_id, reply))
        with pytest.raises(Missing):
            conversations.reply(BotReplyRequest(event_id, bot_id, owner_id + 999, reply))
        assert len([call for call in server.calls if call[0] == "sendMessage"]) == 1


@pytest.mark.parametrize("kind,sender_id", [("group", 987654), ("private", 123999)])
def test_group_or_mismatched_sender_events_cannot_receive_private_replies(
    kind: str, sender_id: int
) -> None:
    server = TelegramServer()
    with server.running() as address:
        event_id, bot_id, owner_id = connected_event(
            server, address, kind=kind, sender_id=sender_id
        )
        assert conversations.event(event_id).message is None
        with pytest.raises(Conflict):
            conversations.reply(
                BotReplyRequest(event_id, bot_id, owner_id, TelegramReply("private"))
            )
        assert not any(method == "sendMessage" for method, _ in server.calls)


def test_private_photo_download_is_bounded_and_rejects_remote_path_traversal() -> None:
    server = TelegramServer()
    with server.running() as address:
        _, bot_id, _ = connected_event(server, address)
        content = b"controlled-telegram-photo"
        server.files["photos/proof.jpg"] = content
        with server.lock:
            server.pending.append(
                {
                    "update_id": 2,
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 987654, "type": "private"},
                        "from": {"id": 987654},
                        "photo": [{"file_id": "proof", "file_size": len(content)}],
                        "caption": "Payment evidence",
                    },
                }
            )
        polling.poll(bot_id)
        event = TelegramInbox.objects.get(bot_id=bot_id, update_id=2)
        downloaded = conversations.file(event.pk, len(content))
        assert downloaded.content is not None and downloaded.content.data == content
        assert server.file_calls == ["photos/proof.jpg"]
        rejected = conversations.file(event.pk, 3)
        assert rejected.content is None and rejected.error_code == "file_limit"
        server.replies["getFile"] = (200, {"ok": True, "result": {"file_path": "../private.png"}})
        unsafe = conversations.file(event.pk, 100)
        assert unsafe.content is None and unsafe.error_code == "invalid_telegram_response"
        assert server.file_calls == ["photos/proof.jpg"]


def test_processed_event_keeps_its_first_timestamp_and_checks_parent() -> None:
    server = TelegramServer()
    with server.running() as address:
        event_id, bot_id, owner_id = connected_event(server, address)
        with pytest.raises(Missing):
            conversations.processed(event_id, uuid4(), owner_id)
        assert TelegramInbox.objects.get(pk=event_id).processed_at is None
        conversations.processed(event_id, bot_id, owner_id)
        observed = TelegramInbox.objects.get(pk=event_id).processed_at
        conversations.processed(event_id, bot_id, owner_id)
        assert TelegramInbox.objects.get(pk=event_id).processed_at == observed
