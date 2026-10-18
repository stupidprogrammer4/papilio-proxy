import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from papilio.core.bootstrap import Bootstrapper as PapilioBootstrapper
from papilio_tasks.apps.schedulers.base import Scheduler
from papilio_tasks.tools.bootstrap import Bootstrapper

from src.modules.billing.receipts.app.outbox_commands import (
    PaymentReceiptOutboxCommand,
)
from src.modules.billing.receipts.app.outbox_interfaces import (
    IReceiptOcrEventPublisher,
)
from src.modules.billing.receipts.domain.outbox import ReceiptOcrOutboxClaim
from src.modules.billing.receipts.tasks.schedulers.outbox import (
    PublishReceiptOcrOutbox,
)

pytestmark = [pytest.mark.billing, pytest.mark.unit]


def test_outbox_scheduler_is_discovered_with_a_persistent_interval():
    schedulers = Bootstrapper(["src.modules"]).classes("schedulers", Scheduler)
    selected = next(
        scheduler
        for scheduler in schedulers
        if scheduler.__name__ == "PublishReceiptOcrOutbox"
    )

    assert selected.schedule == [
        {"interval": 5, "schedule_id": "receipt-ocr-outbox"}
    ]


def test_outbox_scheduler_is_bound_in_its_module_provider():
    providers = PapilioBootstrapper(["src.modules"]).boot_providers()
    receipt_provider = next(
        provider
        for provider in providers
        if type(provider).__name__ == "PaymentReceiptProvider"
    )

    assert any(
        factory.provides.type_hint is PublishReceiptOcrOutbox
        for factory in receipt_provider.factories
    )


def test_outbox_publishes_claimed_receipt_before_marking_it_published():
    claim = ReceiptOcrOutboxClaim(
        outbox_id=7, receipt_id=41, claim_token="claim-token"
    )
    repository = AsyncMock()
    publisher = SimpleNamespace(publish=AsyncMock())
    command = PaymentReceiptOutboxCommand(
        repository, cast(IReceiptOcrEventPublisher, publisher)
    )
    command._claim = AsyncMock(return_value=claim)  # type: ignore[method-assign]
    command._mark_published = AsyncMock(return_value=True)  # type: ignore[method-assign]

    asyncio.run(command.publish_next())

    publisher.publish.assert_awaited_once_with(41)
    command._mark_published.assert_awaited_once_with(claim)


def test_failed_publication_leaves_claim_for_lease_recovery():
    claim = ReceiptOcrOutboxClaim(
        outbox_id=7, receipt_id=41, claim_token="claim-token"
    )
    publisher = SimpleNamespace(
        publish=AsyncMock(side_effect=RuntimeError("NATS unavailable"))
    )
    command = PaymentReceiptOutboxCommand(
        AsyncMock(), cast(IReceiptOcrEventPublisher, publisher)
    )
    command._claim = AsyncMock(return_value=claim)  # type: ignore[method-assign]
    command._mark_published = AsyncMock()  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="NATS unavailable"):
        asyncio.run(command.publish_next())

    command._mark_published.assert_not_awaited()
