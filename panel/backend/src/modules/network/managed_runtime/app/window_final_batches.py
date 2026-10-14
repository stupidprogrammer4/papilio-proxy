"""Settle a shared frozen snapshot for an explicit window batch."""

import secrets
from datetime import UTC, datetime, timedelta

import anyio
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.settings import PapilioSettings
from src.modules.network.core_runtime.interfaces import IRuntimeStateService
from src.modules.network.managed_runtime.app.final_batch_policies import (
    ManagedFinalityBatchPolicy,
)
from src.modules.network.managed_runtime.app.finality_encoding import (
    ManagedFinalityEncoding,
)
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.installations import conflict
from src.modules.network.managed_runtime.app.window_computation import (
    compute_managed_finality_batch,
)
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalBatchCreate,
    ManagedWindowFinalBatchItemOut,
    ManagedWindowFinalBatchOut,
)
from src.modules.network.managed_runtime.domain.installations import (
    ManagedInstallationExpectation,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedBarrierModel,
    ManagedInstallationModel,
    ManagedOperationBatchModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.results import (
    ManagedBarrierIdentity,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedBarrierService,
    IManagedEpochService,
    IManagedInstallationService,
    IManagedOperationBatchService,
    IManagedWindowService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.usage.domain.results import UsageEventIdentity
from src.modules.network.usage.interfaces import (
    IUsageEventService,
    IUsageGrantService,
)
from src.modules.sales.subscriptions.interfaces import (
    ISubscriptionBatchService,
)


class ManagedFinalityBatchCommand:
    def __init__(
        self,
        windows: IManagedWindowService,
        epochs: IManagedEpochService,
        installations: IManagedInstallationService,
        operation_batches: IManagedOperationBatchService,
        barriers: IManagedBarrierService,
        nodes: INodeService,
        states: IRuntimeStateService,
        subscriptions: ISubscriptionBatchService,
        grants: IUsageGrantService,
        events: IUsageEventService,
        settings: PapilioSettings,
    ) -> None:
        self.windows = windows
        self.epochs = epochs
        self.installations = installations
        self.operation_batches = operation_batches
        self.barriers = barriers
        self.nodes = nodes
        self.states = states
        self.subscriptions = subscriptions
        self.grants = grants
        self.events = events
        self.settings = settings

    @handle_conflicts
    @transactional
    async def finalize(
        self,
        code: str,
        key: str,
        data: ManagedWindowFinalBatchCreate,
    ) -> ManagedWindowFinalBatchOut:
        node = await self.nodes.authenticate(code, key)
        window_ids = [item.window_id for item in data.windows]
        rows = await self.windows.by_identities_many(window_ids)
        indexed_windows = {row.window_id: row for row in rows}
        if set(indexed_windows) != set(window_ids):
            raise conflict("managed_window_missing")
        epoch_ids = {row.epoch_id for row in rows}
        if len(epoch_ids) != 1:
            raise conflict("managed_final_epoch_mismatch")
        epoch_id = next(iter(epoch_ids))
        epoch = await self.epochs.find(epoch_id)
        if epoch is None:
            raise conflict("managed_window_epoch_missing")
        installation = await self.installations.find(epoch.installation_id)
        if installation is None or installation.node_id != node.id:
            raise conflict("managed_window_node_mismatch")
        await self.nodes.locked(node.id)
        await self.nodes.authenticate(code, key)
        await self.states.lock_core(installation.core_id)
        installation = await self.installations.locked(installation.id)
        rows = [indexed_windows[window_id] for window_id in window_ids]
        if installation.state != "installed_closed" or any(
            row.epoch_id != epoch.id for row in rows
        ):
            raise conflict("managed_window_installation_mismatch")
        subscription_ids = sorted({row.subscription_id for row in rows})
        subscription_rows = await self.subscriptions.locked_many(
            subscription_ids
        )
        subscriptions = {row.id: row for row in subscription_rows}
        grants = await self.grants.locked_many([row.grant_id for row in rows])
        grants_by_id = {row.id: row for row in grants}
        if (
            set(subscriptions) != set(subscription_ids)
            or len(grants_by_id) != len(rows)
            or not ManagedFinalityBatchPolicy.grant_bindings(
                rows, grants_by_id, node.id, epoch.process_epoch
            )
        ):
            raise conflict("managed_window_grant_mismatch")
        expectation = await self._expectation(installation)
        computed = await compute_managed_finality_batch(
            data,
            tuple(
                ManagedWindowModel.model_validate(row.model_dump())
                for row in rows
            ),
            expectation,
            epoch.process_epoch,
            self.settings.configuration_encryption_key,
        )
        digest = computed.request_sha256
        now = datetime.now(UTC).replace(tzinfo=None)
        computed_by_window = {
            item.window_id: item for item in computed.windows
        }
        submitted_by_window = {item.window_id: item for item in data.windows}
        if computed_by_window.keys() != set(window_ids):
            raise conflict("managed_final_window_mismatch")
        digest_by_window = {
            item.window_id: item.request_sha256 for item in computed.windows
        }
        deltas = {
            item.window_id: item.grant_delta for item in computed.windows
        }
        frozen_by_window = {
            item.window_id: (
                item.original_snapshot.snapshot.frozen_at.astimezone(
                    UTC
                ).replace(tzinfo=None)
            )
            for item in computed.windows
        }
        if any(
            frozen_by_window[row.window_id] < row.issued_at
            or frozen_by_window[row.window_id]
            > now + timedelta(seconds=expectation.clock_skew_seconds)
            for row in rows
        ):
            raise conflict("managed_final_receipt_state_conflict")
        batch = await self.operation_batches.by_identity(
            installation.id, "final_windows", data.batch_request_key
        )
        barrier_identities = [
            ManagedBarrierIdentity(
                epoch.id,
                computed_by_window[
                    window_id
                ].original_snapshot.snapshot.barrier_id,
            )
            for window_id in window_ids
        ]
        existing_barriers = await self.barriers.by_identities_many(
            barrier_identities
        )
        barriers_by_id = {row.barrier_id: row for row in existing_barriers}
        barriers_by_window: dict[str, ManagedBarrierModel] = {}
        for window_id in window_ids:
            barrier_id = computed_by_window[
                window_id
            ].original_snapshot.snapshot.barrier_id
            barrier = barriers_by_id.get(barrier_id)
            if barrier is not None:
                barriers_by_window[window_id] = barrier
        identities = [
            UsageEventIdentity(node.id, "managed:" + row.window_id)
            for row in rows
        ]
        existing_events = await self.events.by_identities_many(identities)
        events_by_identity = {row.event_id: row for row in existing_events}
        if batch is not None:
            if (
                batch.epoch_id != epoch.id
                or batch.request_sha256 != digest
                or batch.item_count != len(rows)
                or len(barriers_by_window) != len(rows)
                or any(
                    barriers_by_window[window_id].request_sha256
                    != digest_by_window[window_id]
                    or barriers_by_window[window_id].snapshot_sha256
                    != submitted_by_window[
                        window_id
                    ].submission.receipt.snapshot_sha256
                    for window_id in window_ids
                )
            ):
                raise conflict("managed_final_batch_reused")
            return ManagedFinalityBatchPolicy.replay(
                data,
                rows,
                grants_by_id,
                events_by_identity,
                barriers_by_window,
                epoch.process_epoch,
                digest_by_window,
            )
        if existing_barriers or existing_events:
            raise conflict("managed_final_receipt_reused")
        grant_updates, usage_events, subscription_updates = (
            ManagedFinalityBatchPolicy.settlement(
                rows,
                grants_by_id,
                subscriptions,
                deltas,
                digest_by_window,
                frozen_by_window,
            )
        )
        encrypted_items = await anyio.to_thread.run_sync(
            ManagedFinalityEncoding.encrypt_receipts,
            tuple(data.windows),
            self.settings.configuration_encryption_key,
        )
        encrypted_by_window = {
            item.window_id: item.encrypted_receipt for item in encrypted_items
        }
        created_barriers_by_window = {
            window_id: ManagedBarrierModel(
                epoch_id=epoch.id,
                barrier_id=computed_by_window[
                    window_id
                ].original_snapshot.snapshot.barrier_id,
                acceptance_id=secrets.token_hex(16),
                snapshot_sha256=submitted_by_window[
                    window_id
                ].submission.receipt.snapshot_sha256,
                request_sha256=digest_by_window[window_id],
                frozen_at=frozen_by_window[window_id],
                accepted_at=now,
                encrypted_receipt=encrypted_by_window[window_id],
            )
            for window_id in window_ids
        }
        barrier_rows = list(created_barriers_by_window.values())
        await self.barriers.create_many(barrier_rows)
        await self.events.create_many(usage_events)
        updated_grants = await self.grants.change_many(grant_updates)
        if subscription_updates:
            await self.subscriptions.update_used_many(subscription_updates)
        await self.operation_batches.create(
            ManagedOperationBatchModel(
                installation_id=installation.id,
                epoch_id=epoch.id,
                operation="final_windows",
                request_key=data.batch_request_key,
                request_sha256=digest,
                item_count=len(rows),
                accepted_at=now,
            )
        )
        updated_by_id = {row.id: row for row in updated_grants}
        result_rows = [
            ManagedWindowFinalBatchItemOut(
                window_id=window.window_id,
                result=ManagedFinalityBatchPolicy.result(
                    window,
                    updated_by_id[window.grant_id],
                    created_barriers_by_window[window.window_id],
                    epoch.process_epoch,
                ),
            )
            for window in rows
        ]
        return ManagedWindowFinalBatchOut(
            batch_request_key=data.batch_request_key,
            windows=result_rows,
        )

    async def _expectation(
        self, installation: ManagedInstallationModel
    ) -> ManagedInstallationExpectation:
        result = await anyio.to_thread.run_sync(
            ManagedInstallationEncoding.decode,
            installation.encrypted_manifest,
            self.settings.configuration_encryption_key,
        )
        return result
