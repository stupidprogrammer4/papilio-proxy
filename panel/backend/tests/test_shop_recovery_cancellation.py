"""Cancelled or expired work fences the previous worker's real application path."""

from datetime import timedelta

import pytest
from django.utils import timezone
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_customers import configured_event
from test_shop_recovery import failed_work, recovery

from papilio_panel.modules.shop.models import InboxWork, OutgoingMessage, ShopCustomer, WorkRecovery
from papilio_panel.modules.shop.providers import execution, sending
from papilio_panel.shared.errors import Conflict

pytestmark = pytest.mark.django_db(transaction=True)


def test_active_work_denies_recovery_and_expired_cancellation_rolls_back_stale_effects() -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        event_id = configured_event(owner, server, address)
        work = InboxWork.objects.create(event_id=event_id)
        claimed = execution.begin(work.id)
        assert claimed is not None
        root = f"/api/v1/bots/{claimed.event.bot.id}/shop/work/{work.id}"
        active = owner.get(root).json()
        assert active["actions"] == []
        assert (
            owner.post(
                root + "/recoveries", recovery(active["revision"], "cancel"), format="json"
            ).status_code
            == 409
        )
        assert WorkRecovery.objects.count() == 0
        InboxWork.objects.filter(pk=work.id).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        current = owner.get(root).json()
        cancelled = owner.post(
            root + "/recoveries", recovery(current["revision"], "cancel"), format="json"
        )
        assert cancelled.status_code == 201 and cancelled.json()["work"]["status"] == "cancelled"
        assert execution.begin(work.id) is None
        with pytest.raises(Conflict):
            execution.process(claimed)
        assert ShopCustomer.objects.count() == 0 and OutgoingMessage.objects.count() == 0
        work.refresh_from_db()
        assert work.status == "cancelled" and work.event.processed_at is not None


def test_cancelled_message_denies_the_late_sender_before_external_http() -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        work = failed_work(owner, server, address)
        message = OutgoingMessage.objects.get(event=work.event)
        claimed = sending.begin(message.id)
        assert claimed is not None
        root = f"/api/v1/bots/{message.bot_id}/shop/messages/{message.id}"
        current = owner.get(root).json()
        assert current["actions"] == []
        assert (
            owner.post(
                root + "/recoveries", recovery(current["revision"], "cancel"), format="json"
            ).status_code
            == 409
        )
        OutgoingMessage.objects.filter(pk=message.id).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        expired = owner.get(root).json()
        assert set(expired["actions"]) == {"retry", "cancel"}
        cancelled = owner.post(
            root + "/recoveries", recovery(expired["revision"], "cancel"), format="json"
        )
        assert cancelled.status_code == 201
        assert sending.send(claimed).retry_after_seconds is None
        assert sending.begin(message.id) is None
        message.refresh_from_db()
        assert message.status == "cancelled"
        assert not any(method == "sendMessage" for method, _ in server.calls)
