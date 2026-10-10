"""Atomic original-receipt settlement for one explicitly named window."""

import asyncio
import secrets
from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import encrypt

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.interfaces import IRuntimeStateService
from src.modules.network.managed_runtime.app.finality_encoding import (
    ManagedFinalityEncoding,
)
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.installations import conflict
from src.modules.network.managed_runtime.app.wire_encoding import (
    ManagedWireEncoding,
)
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalOut,
    ManagedWindowFinalSubmission,
)
from src.modules.network.managed_runtime.domain.contracts import (
    ManagedPredecessor,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedBarrierModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedBarrierService,
    IManagedEpochService,
    IManagedInstallationService,
    IManagedWindowService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.usage.domain.models import (
    UsageEventModel,
    UsageGrantModel,
)
from src.modules.network.usage.infra.mysql import (
    UsageEventRepository,
    UsageGrantRepository,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class ManagedFinalityCommand:
    def __init__(
        self,
        windows: IManagedWindowService,
        epochs: IManagedEpochService,
        installations: IManagedInstallationService,
        barriers: IManagedBarrierService,
        nodes: INodeService,
        states: IRuntimeStateService,
        subscriptions: SubscriptionRepository,
        grants: UsageGrantRepository,
        events: UsageEventRepository,
        settings: PapilioSettings,
    ) -> None:
        self.windows, self.epochs = windows, epochs
        self.installations, self.barriers = installations, barriers
        self.nodes, self.states = nodes, states
        self.subscriptions, self.grants, self.events = (
            subscriptions,
            grants,
            events,
        )
        self.settings = settings

    @staticmethod
    def result(
        window: ManagedWindowModel,
        grant: UsageGrantModel,
        barrier: ManagedBarrierModel,
        epoch: str,
    ) -> ManagedWindowFinalOut:
        return ManagedWindowFinalOut(
            window_id=window.window_id,
            grant_id=grant.id,
            acceptance=ManagedPredecessor(
                acceptance_id=barrier.acceptance_id,
                epoch=epoch,
                profile_id=window.profile_id,
                barrier_id=barrier.barrier_id,
                snapshot_sha256=barrier.snapshot_sha256,
            ),
            upload_bytes=grant.upload_bytes,
            download_bytes=grant.download_bytes,
        )

    @handle_conflicts
    @transactional
    async def finalize(
        self,
        code: str,
        key: str,
        window_id: str,
        data: ManagedWindowFinalSubmission,
    ) -> ManagedWindowFinalOut:
        node = await self.nodes.authenticate(code, key)
        hint = await self.windows.by_identity(window_id)
        if hint is None:
            raise conflict("managed_window_missing")
        epoch = await self.epochs.find(hint.epoch_id)
        if epoch is None:
            raise conflict("managed_window_epoch_missing")
        installation = await self.installations.find(epoch.installation_id)
        if installation is None or installation.node_id != node.id:
            raise conflict("managed_window_node_mismatch")
        await self.nodes.locked(node.id)
        await self.nodes.authenticate(code, key)
        await self.states.lock_core(installation.core_id)
        subscription = await self.subscriptions.locked(hint.subscription_id)
        if subscription is None:
            raise conflict("managed_window_subscription_missing")
        installation = await self.installations.locked(installation.id)
        window = await self.windows.locked(hint.id)
        if window is None:
            raise conflict("managed_window_missing")
        grant = await self.grants.locked(window.grant_id)
        if (
            grant is None
            or installation.state != "installed_closed"
            or grant.node_id != node.id
            or grant.subscription_id != subscription.id
            or grant.profile_id != window.profile_id
            or grant.generation != window.generation
            or grant.mode != "reserved"
            or grant.process_epoch != epoch.process_epoch
            or grant.allocated_bytes != window.allocated_bytes
        ):
            raise conflict("managed_window_grant_mismatch")
        expectation = await asyncio.to_thread(
            ManagedInstallationEncoding.decode,
            installation.encrypted_manifest,
            self.settings.configuration_encryption_key,
        )
        try:
            original = await asyncio.to_thread(
                ManagedFinalityEncoding.verify,
                data,
                ManagedWindowModel.model_validate(window.model_dump()),
                expectation,
                epoch.process_epoch,
                self.settings.configuration_encryption_key,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_final_receipt_invalid") from None
        digest = await asyncio.to_thread(
            ManagedFinalityEncoding.request_digest, data
        )
        existing = await self.barriers.by_identity(
            epoch.id, original.snapshot.barrier_id
        )
        if existing is not None:
            if (
                existing.request_sha256 != digest
                or existing.snapshot_sha256 != data.receipt.snapshot_sha256
                or not grant.is_closed
            ):
                raise conflict("managed_final_receipt_reused")
            return self.result(window, grant, existing, epoch.process_epoch)
        frozen = original.snapshot.frozen_at.astimezone(UTC).replace(
            tzinfo=None
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        if (
            grant.is_closed
            or frozen < window.issued_at
            or frozen > now + timedelta(seconds=expectation.clock_skew_seconds)
        ):
            raise conflict("managed_final_receipt_state_conflict")
        deltas = await asyncio.to_thread(
            ManagedWireEncoding.grant_deltas, original.snapshot
        )
        counters = {item.window_id: item for item in deltas}[window.window_id]
        delta = counters.upload_bytes + counters.download_bytes
        if (
            grant.sequence != 0
            or grant.upload_bytes != 0
            or grant.download_bytes != 0
            or delta > grant.allocated_bytes
            or grant.generation == subscription.renewal_count
            and subscription.used_bytes + delta > 2**63 - 1
        ):
            raise conflict("managed_final_counter_conflict")
        encrypted = await asyncio.to_thread(
            encrypt,
            data.original_receipt,
            self.settings.configuration_encryption_key,
        )
        await self.events.create(
            UsageEventModel(
                grant_id=grant.id,
                subscription_id=grant.subscription_id,
                node_id=grant.node_id,
                generation=grant.generation,
                event_id="managed:" + window.window_id,
                payload_hash=digest,
                sequence=1,
                upload_bytes=counters.upload_bytes,
                download_bytes=counters.download_bytes,
                delta_upload_bytes=counters.upload_bytes,
                delta_download_bytes=counters.download_bytes,
                delta_bytes=delta,
                final=True,
                sampled_at=frozen,
            )
        )
        grant = await self.grants.change(
            grant,
            UsageGrantModel.patch(
                upload_bytes=counters.upload_bytes,
                download_bytes=counters.download_bytes,
                sequence=1,
                sampled_at=frozen,
                is_closed=True,
            ),
        )
        if grant.generation == subscription.renewal_count:
            await self.subscriptions.update_existing(
                subscription,
                SubscriptionModel.patch(
                    used_bytes=subscription.used_bytes + delta
                ),
            )
        barrier = await self.barriers.create(
            ManagedBarrierModel(
                epoch_id=epoch.id,
                barrier_id=original.snapshot.barrier_id,
                acceptance_id=secrets.token_hex(16),
                snapshot_sha256=data.receipt.snapshot_sha256,
                request_sha256=digest,
                frozen_at=frozen,
                accepted_at=now,
                encrypted_receipt=encrypted,
            )
        )
        return self.result(window, grant, barrier, epoch.process_epoch)
