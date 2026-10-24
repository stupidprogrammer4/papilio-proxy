"""Native independent transactions serialize recovery identities and revisions."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import close_old_connections, connection
from telegram_server import TelegramServer
from test_nodes import owner_client
from test_shop_recovery import failed_work

from papilio_panel.modules.shop.domain import RecoveryAction
from papilio_panel.modules.shop.models import (
    InboxWork,
    MessageRecovery,
    OutgoingMessage,
    WorkRecovery,
)
from papilio_panel.modules.shop.providers import (
    message_inspection,
    message_recovery,
    sending,
    work_inspection,
    work_recovery,
)
from papilio_panel.modules.shop.recovery_contracts import (
    MessageRecoveryInput,
    RecoveryDefinition,
    WorkRecoveryInput,
)
from papilio_panel.shared.errors import Conflict

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_recoveries_commit_one_audit_and_one_state_change(same_key: bool) -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        work = failed_work(owner, server, address)
        bot_id, actor_id = work.event.bot.id, work.event.bot.owner_id
        record = work_inspection.read(bot_id, work.id, actor_id)
        key = uuid4()
        first = WorkRecoveryInput(
            actor_id,
            bot_id,
            work.id,
            RecoveryDefinition(key, record.revision, RecoveryAction.RETRY),
        )
        second = (
            first
            if same_key
            else WorkRecoveryInput(
                actor_id,
                bot_id,
                work.id,
                RecoveryDefinition(uuid4(), record.revision, RecoveryAction.CANCEL),
            )
        )
        barrier = Barrier(2, timeout=10)

        def recover(values: WorkRecoveryInput) -> tuple[bool, bool]:
            close_old_connections()
            try:
                barrier.wait()
                result = work_recovery.recover(values)
                return True, result.created
            except Conflict:
                return False, False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(recover, (first, second)))
        assert sum(created for _, created in results) == 1
        assert sum(succeeded for succeeded, _ in results) == (2 if same_key else 1)
        connection.close()
        stored = InboxWork.objects.get(pk=work.id)
        assert stored.revision == record.revision + 1
        assert stored.status in {"queued", "cancelled"}
        assert WorkRecovery.objects.filter(work=stored).count() == 1


@pytest.mark.parametrize("same_key", [False, True])
def test_concurrent_message_recoveries_preserve_one_audit_and_original_payload(
    same_key: bool,
) -> None:
    server = TelegramServer()
    with server.running() as address:
        owner = owner_client()
        work = failed_work(owner, server, address)
        message = OutgoingMessage.objects.get(event=work.event)
        original = bytes(message.payload_ciphertext)
        claim = sending.begin(message.id)
        assert claim is not None
        server.replies["sendMessage"] = (500, {"ok": False})
        sending.send(claim)
        record = message_inspection.read(message.bot_id, message.id, message.owner_id)
        first = MessageRecoveryInput(
            message.owner_id,
            message.bot_id,
            message.id,
            RecoveryDefinition(uuid4(), record.revision, RecoveryAction.RETRY),
        )
        second = (
            first
            if same_key
            else MessageRecoveryInput(
                message.owner_id,
                message.bot_id,
                message.id,
                RecoveryDefinition(uuid4(), record.revision, RecoveryAction.CANCEL),
            )
        )
        barrier = Barrier(2, timeout=10)

        def recover(values: MessageRecoveryInput) -> tuple[bool, bool]:
            close_old_connections()
            try:
                barrier.wait()
                result = message_recovery.recover(values)
                return True, result.created
            except Conflict:
                return False, False
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(recover, (first, second)))
        assert sum(created for _, created in results) == 1
        assert sum(succeeded for succeeded, _ in results) == (2 if same_key else 1)
        connection.close()
        stored = OutgoingMessage.objects.get(pk=message.id)
        assert stored.revision == record.revision + 1
        assert bytes(stored.payload_ciphertext) == original
        assert MessageRecovery.objects.filter(message=stored).count() == 1
