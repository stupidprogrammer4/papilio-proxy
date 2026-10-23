"""Native outgoing leases distinguish paused work, known errors and send uncertainty."""

from datetime import timedelta

import pytest
from django.utils import timezone
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_customers import configured_event
from test_shop_purchases import execute

from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage
from papilio_panel.modules.shop.providers import sending
from papilio_panel.shared.errors import ApplicationError

pytestmark = pytest.mark.django_db(transaction=True)


def test_pause_between_claim_and_send_preserves_reply_without_http() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        execute(InboxWork.objects.create(event_id=event_id))
        message = OutgoingMessage.objects.get()
        claim = sending.begin(message.id)
        assert claim is not None
        path = f"/api/v1/bots/{message.bot_id}/shop"
        current = client.get(path).json()
        paused = current["definition"] | {
            "delivery_enabled": False,
            "expected_revision": current["revision"],
        }
        assert client.put(path, paused, format="json").status_code == 200
        outcome = sending.send(claim)
        assert outcome.retry_after_seconds is None
        message.refresh_from_db()
        assert message.status == "queued" and message.attempts == 0
        assert message.lease_token is None and message.dispatched_at is None
        assert not server.messages


def test_known_pre_http_error_does_not_become_an_ambiguous_send() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        execute(InboxWork.objects.create(event_id=event_id))
        message = OutgoingMessage.objects.get()
        claim = sending.begin(message.id)
        assert claim is not None
        # Native bot owner guard fails before the gateway can send anything.
        from django.contrib.auth import get_user_model

        get_user_model().objects.filter(pk=message.owner_id).update(is_active=False)
        try:
            sending.send(claim)
        except ApplicationError as error:
            sending.fail(claim, error.code)
        message.refresh_from_db()
        assert message.status == "failed"
        assert message.error_code == "invalid_credentials"
        assert not server.messages


def test_retry_wait_and_expired_sender_hold_do_not_send_again() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        execute(InboxWork.objects.create(event_id=event_id))
        message = OutgoingMessage.objects.get()
        claim = sending.begin(message.id)
        assert claim is not None
        server.replies["sendMessage"] = (429, {"ok": False, "parameters": {"retry_after": 45}})
        outcome = sending.send(claim)
        assert outcome.retry_after_seconds == 45
        message.refresh_from_db()
        assert message.status == "retry" and message.retry_at > timezone.now()
        assert sending.begin(message.id) is None
        # A sender that disappeared after its lease began has an unknown HTTP outcome.
        OutgoingMessage.objects.filter(pk=message.id).update(
            status="sending", lease_until=timezone.now() - timedelta(seconds=1)
        )
        assert sending.begin(message.id) is None
        message.refresh_from_db()
        assert message.status == "ambiguous" and message.error_code == "sender_lease_expired"
        assert len([method for method, _ in server.calls if method == "sendMessage"]) == 1


def test_lowered_attempt_limit_stops_before_another_http_request() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        execute(InboxWork.objects.create(event_id=event_id))
        message = OutgoingMessage.objects.get()
        OutgoingMessage.objects.filter(pk=message.id).update(attempts=5)
        assert sending.begin(message.id) is None
        message.refresh_from_db()
        assert message.status == "failed" and message.error_code == "attempt_limit_reached"
        assert not server.messages


def test_uncertain_last_attempt_still_records_ambiguity_in_hold_mode() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        execute(InboxWork.objects.create(event_id=event_id))
        message = OutgoingMessage.objects.get()
        path = f"/api/v1/bots/{message.bot_id}/shop"
        current = client.get(path).json()
        definition = current["definition"] | {
            "max_attempts": 1,
            "expected_revision": current["revision"],
        }
        assert client.put(path, definition, format="json").status_code == 200
        claim = sending.begin(message.id)
        assert claim is not None
        server.replies["sendMessage"] = (500, {"ok": False})
        outcome = sending.send(claim)
        message.refresh_from_db()
        assert outcome.retry_after_seconds is None
        assert message.status == "ambiguous" and message.attempts == 1
        assert sending.begin(message.id) is None


def test_expired_sender_cannot_resume_and_send_after_delivery_is_held() -> None:
    server = TelegramServer()
    with server.running() as address:
        client = owner_client()
        event_id = configured_event(client, server, address)
        execute(InboxWork.objects.create(event_id=event_id))
        message = OutgoingMessage.objects.get()
        claim = sending.begin(message.id)
        assert claim is not None
        OutgoingMessage.objects.filter(pk=message.id).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        assert sending.begin(message.id) is None
        outcome = sending.send(claim)
        message.refresh_from_db()
        assert message.status == "ambiguous" and outcome.retry_after_seconds is None
        assert not server.messages
