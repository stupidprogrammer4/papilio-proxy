"""Real HTTP protocol validation against a controlled external Telegram server."""

import pytest
from telegram_server import TelegramServer
from test_bots import TEST_TOKEN

from papilio_panel.modules.bots.domain import BotRuntime, TelegramConnection
from papilio_panel.modules.bots.infra.telegram import NativeTelegramGateway


@pytest.mark.parametrize("body", [None, [], {"parameters": []}, {"parameters": "unexpected"}])
def test_malformed_rate_limit_metadata_is_a_safe_error(body: object) -> None:
    server = TelegramServer()
    server.replies["getUpdates"] = (429, body)
    with server.running() as address:
        connection = TelegramConnection(token=TEST_TOKEN, runtime=BotRuntime(api_base_url=address))
        result = NativeTelegramGateway().updates(connection, 0)
        assert result.error_code == "rate_limited"
        assert result.retry_after_seconds is None


@pytest.mark.parametrize(
    "updates",
    [
        [{"update_id": True}],
        [{"update_id": -1}],
        [{"update_id": 1}, {"update_id": 1, "different": True}],
        [{"update_id": 9223372036854775807}],
        {"unexpected": True},
    ],
)
def test_malformed_update_batches_do_not_produce_accepted_updates(updates: object) -> None:
    server = TelegramServer()
    server.replies["getUpdates"] = (200, {"ok": True, "result": updates})
    with server.running() as address:
        connection = TelegramConnection(token=TEST_TOKEN, runtime=BotRuntime(api_base_url=address))
        result = NativeTelegramGateway().updates(connection, 0)
        assert result.error_code == "invalid_telegram_response"
        assert not result.updates


def test_supported_message_fields_preserve_receipts_and_ignore_unmodelled_quantities() -> None:
    server = TelegramServer()
    payload = {
        "update_id": 12,
        "message": {
            "message_id": 5,
            "chat": {"id": 456789, "type": "private"},
            "from": {"id": 456789, "is_bot": False, "first_name": "Customer"},
            "caption": "Payment receipt",
            "photo": [
                {
                    "file_id": "receipt-file",
                    "file_unique_id": "receipt-identity",
                    "width": 800,
                    "height": 600,
                }
            ],
            "location": {"latitude": 35.123456, "longitude": 51.123456},
        },
    }
    server.replies["getUpdates"] = (200, {"ok": True, "result": [payload]})
    with server.running() as address:
        connection = TelegramConnection(token=TEST_TOKEN, runtime=BotRuntime(api_base_url=address))
        result = NativeTelegramGateway().updates(connection, 0)
        assert result.error_code is None
        retained = {item.update_id: item.payload for item in result.updates}[12]["message"]
        assert retained["photo"][0]["file_id"] == "receipt-file"
        assert retained["caption"] == "Payment receipt"
        assert "location" not in retained


def test_callback_payload_keeps_authoritative_sender_and_button_data() -> None:
    server = TelegramServer()
    payload = {
        "update_id": 15,
        "callback_query": {
            "id": "callback-id",
            "from": {"id": 456789},
            "data": "shop:products",
            "message": {"message_id": 22, "chat": {"id": 456789, "type": "private"}},
        },
    }
    server.replies["getUpdates"] = (200, {"ok": True, "result": [payload]})
    with server.running() as address:
        connection = TelegramConnection(token=TEST_TOKEN, runtime=BotRuntime(api_base_url=address))
        result = NativeTelegramGateway().updates(connection, 0)
        assert result.error_code is None
        retained = {item.update_id: item.payload for item in result.updates}[15]["callback_query"]
        assert retained["from"]["id"] == 456789
        assert retained["data"] == "shop:products"
