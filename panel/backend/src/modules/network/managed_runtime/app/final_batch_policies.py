"""Settlement and replay policies for shared managed snapshots."""

from datetime import datetime

from src.modules.network.managed_runtime.app.installations import conflict
from src.modules.network.managed_runtime.domain.barriers import (
    ManagedWindowFinalBatchCreate,
    ManagedWindowFinalBatchItemOut,
    ManagedWindowFinalBatchOut,
    ManagedWindowFinalOut,
)
from src.modules.network.managed_runtime.domain.contracts import (
    ManagedPredecessor,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedBarrierModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.wire import ManagedGrantDelta
from src.modules.network.usage.domain.models import (
    UsageEventModel,
    UsageGrantModel,
)
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.domain.results import (
    SubscriptionUsageUpdate,
)


class ManagedFinalityBatchPolicy:
    @staticmethod
    def grant_bindings(
        windows: list[ManagedWindowModel],
        grants: dict[int, UsageGrantModel],
        node_id: int,
        process_epoch: str,
    ) -> bool:
        return all(
            grant is not None
            and grant.node_id == node_id
            and grant.subscription_id == window.subscription_id
            and grant.profile_id == window.profile_id
            and grant.generation == window.generation
            and grant.mode == "reserved"
            and grant.process_epoch == process_epoch
            and grant.allocated_bytes == window.allocated_bytes
            for window in windows
            for grant in (grants.get(window.grant_id),)
        )

    @staticmethod
    def settlement(
        windows: list[ManagedWindowModel],
        grants: dict[int, UsageGrantModel],
        subscriptions: dict[int, SubscriptionModel],
        deltas: dict[str, ManagedGrantDelta],
        digests: dict[str, str],
        sampled_at_by_window: dict[str, datetime],
    ) -> tuple[
        list[UsageGrantModel],
        list[UsageEventModel],
        list[SubscriptionUsageUpdate],
    ]:
        grant_updates: list[UsageGrantModel] = []
        events: list[UsageEventModel] = []
        usage_by_subscription: dict[int, int] = {}
        for window in windows:
            grant = grants[window.grant_id]
            delta = deltas[window.window_id]
            total = delta.upload_bytes + delta.download_bytes
            if (
                grant.is_closed
                or grant.sequence != 0
                or grant.upload_bytes != 0
                or grant.download_bytes != 0
                or total > grant.allocated_bytes
            ):
                raise conflict("managed_final_counter_conflict")
            events.append(
                UsageEventModel(
                    grant_id=grant.id,
                    subscription_id=grant.subscription_id,
                    node_id=grant.node_id,
                    generation=grant.generation,
                    event_id="managed:" + window.window_id,
                    payload_hash=digests[window.window_id],
                    sequence=1,
                    upload_bytes=delta.upload_bytes,
                    download_bytes=delta.download_bytes,
                    delta_upload_bytes=delta.upload_bytes,
                    delta_download_bytes=delta.download_bytes,
                    delta_bytes=total,
                    final=True,
                    sampled_at=sampled_at_by_window[window.window_id],
                )
            )
            grant_updates.append(
                UsageGrantModel.patch(
                    id=grant.id,
                    upload_bytes=delta.upload_bytes,
                    download_bytes=delta.download_bytes,
                    sequence=1,
                    sampled_at=sampled_at_by_window[window.window_id],
                    is_closed=True,
                )
            )
            if (
                grant.generation
                == subscriptions[grant.subscription_id].renewal_count
            ):
                usage_by_subscription[grant.subscription_id] = (
                    usage_by_subscription.get(grant.subscription_id, 0) + total
                )
        updates: list[SubscriptionUsageUpdate] = []
        for subscription_id, delta_bytes in usage_by_subscription.items():
            subscription = subscriptions[subscription_id]
            used_bytes = subscription.used_bytes + delta_bytes
            if used_bytes > 2**63 - 1:
                raise conflict("managed_final_counter_conflict")
            updates.append(
                SubscriptionUsageUpdate(subscription_id, used_bytes)
            )
        return grant_updates, events, updates

    @staticmethod
    def replay(
        data: ManagedWindowFinalBatchCreate,
        windows: list[ManagedWindowModel],
        grants: dict[int, UsageGrantModel],
        events: dict[str, UsageEventModel],
        barriers: dict[str, ManagedBarrierModel],
        epoch: str,
        digests: dict[str, str],
    ) -> ManagedWindowFinalBatchOut:
        result_items: list[ManagedWindowFinalBatchItemOut] = []
        for window in windows:
            grant = grants[window.grant_id]
            event = events.get("managed:" + window.window_id)
            if (
                event is None
                or window.window_id not in barriers
                or not grant.is_closed
                or event.grant_id != grant.id
                or event.payload_hash != digests[window.window_id]
                or not event.final
                or event.sequence != grant.sequence
                or event.upload_bytes != grant.upload_bytes
                or event.download_bytes != grant.download_bytes
                or event.delta_bytes
                != event.delta_upload_bytes + event.delta_download_bytes
            ):
                raise conflict("managed_final_batch_replay_incomplete")
            result_items.append(
                ManagedWindowFinalBatchItemOut(
                    window_id=window.window_id,
                    result=ManagedFinalityBatchPolicy.result(
                        window, grant, barriers[window.window_id], epoch
                    ),
                )
            )
        return ManagedWindowFinalBatchOut(
            batch_request_key=data.batch_request_key,
            windows=result_items,
        )

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
