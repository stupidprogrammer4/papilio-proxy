"""Native historical revocation acceptance after authoritative finality."""

import asyncio
from datetime import UTC, datetime, timedelta

from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import encrypt

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.core_runtime.interfaces import IRuntimeStateService
from src.modules.network.managed_runtime.app.installation_encoding import (
    ManagedInstallationEncoding,
)
from src.modules.network.managed_runtime.app.installations import conflict
from src.modules.network.managed_runtime.app.revocation_encoding import (
    ManagedRevocationEncoding,
)
from src.modules.network.managed_runtime.app.window_encoding import (
    ManagedWindowEncoding,
)
from src.modules.network.managed_runtime.domain.models import (
    ManagedBarrierModel,
    ManagedRevocationModel,
    ManagedWindowModel,
)
from src.modules.network.managed_runtime.domain.revocations import (
    ManagedRevocationOut,
    ManagedRevocationSubmission,
)
from src.modules.network.managed_runtime.interfaces import (
    IManagedBarrierService,
    IManagedEpochService,
    IManagedInstallationService,
    IManagedRevocationService,
    IManagedWindowService,
)
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.provisioning.domain.managed import (
    ManagedRevocationEvidence,
)
from src.modules.network.provisioning.infra.mysql import (
    ProvisionRequestRepository,
    ProvisionTaskRepository,
)
from src.modules.network.provisioning.interfaces import IProvisioningCommand
from src.modules.network.usage.infra.mysql import UsageGrantRepository
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class ManagedRevocationCommand:
    def __init__(
        self,
        revocations: IManagedRevocationService,
        windows: IManagedWindowService,
        epochs: IManagedEpochService,
        installations: IManagedInstallationService,
        barriers: IManagedBarrierService,
        nodes: INodeService,
        states: IRuntimeStateService,
        customers: ICustomerService,
        subscriptions: SubscriptionRepository,
        requests: ProvisionRequestRepository,
        tasks: ProvisionTaskRepository,
        grants: UsageGrantRepository,
        provisioning: IProvisioningCommand,
        settings: PapilioSettings,
    ) -> None:
        self.revocations, self.windows, self.epochs = (
            revocations,
            windows,
            epochs,
        )
        self.installations, self.barriers = installations, barriers
        self.nodes, self.states, self.customers = nodes, states, customers
        self.subscriptions, self.requests, self.tasks = (
            subscriptions,
            requests,
            tasks,
        )
        self.grants, self.provisioning, self.settings = (
            grants,
            provisioning,
            settings,
        )

    @handle_conflicts
    @transactional
    async def acknowledge(
        self,
        code: str,
        key: str,
        window_id: str,
        data: ManagedRevocationSubmission,
    ) -> ManagedRevocationOut:
        node = await self.nodes.authenticate(code, key)
        hint = await self.windows.by_identity(window_id)
        if hint is None or hint.provision_task_id is None:
            raise conflict("managed_paid_window_missing")
        hint_id, epoch_id, subscription_id = (
            hint.id,
            hint.epoch_id,
            hint.subscription_id,
        )
        initial_epoch = await self.epochs.find(epoch_id)
        if initial_epoch is None:
            raise conflict("managed_window_epoch_missing")
        initial = await self.installations.find(initial_epoch.installation_id)
        subscription_hint = await self.subscriptions.get_by_id(subscription_id)
        if (
            initial is None
            or initial.node_id != node.id
            or subscription_hint is None
        ):
            raise conflict("managed_window_node_mismatch")
        installation_id, core_id, node_id = (
            initial.id,
            initial.core_id,
            node.id,
        )
        try:
            original_hint = await asyncio.to_thread(
                ManagedWindowEncoding.output,
                ManagedWindowModel.model_validate(hint.model_dump()),
                self.settings.configuration_encryption_key,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_paid_claim_missing") from None
        claim = original_hint.provision_claim
        if claim is None or claim.task_id != hint.provision_task_id:
            raise conflict("managed_paid_claim_missing")
        customer_id = subscription_hint.customer_id
        payer_id = subscription_hint.payer_customer_id
        await self.customers.locked_many(
            sorted({customer_id, payer_id or customer_id})
        )
        await self.nodes.locked(node_id)
        await self.nodes.authenticate(code, key)
        await self.states.lock_core(core_id)
        subscription = await self.subscriptions.locked(subscription_id)
        if (
            subscription is None
            or subscription.customer_id != customer_id
            or subscription.payer_customer_id != payer_id
        ):
            raise conflict("provision_subscription_owner_changed")
        request = await self.requests.locked(claim.request_id)
        task = await self.tasks.locked(claim.task_id)
        installation = await self.installations.locked(installation_id)
        epoch = await self.epochs.locked(epoch_id)
        window = await self.windows.locked(hint_id)
        if (
            epoch is None
            or epoch.installation_id != installation_id
            or installation.core_id != core_id
            or installation.node_id != node_id
            or installation.state != "installed_closed"
            or window is None
            or window.window_id != window_id
            or window.epoch_id != epoch_id
            or window.subscription_id != subscription_id
            or window.provision_task_id != claim.task_id
        ):
            raise conflict("managed_revocation_window_mismatch")
        detached = ManagedWindowModel.model_validate(window.model_dump())
        expectation = await asyncio.to_thread(
            ManagedInstallationEncoding.decode,
            installation.encrypted_manifest,
            self.settings.configuration_encryption_key,
        )
        try:
            original = await asyncio.to_thread(
                ManagedWindowEncoding.output,
                detached,
                self.settings.configuration_encryption_key,
            )
            revocation = await asyncio.to_thread(
                ManagedRevocationEncoding.verify_original,
                data,
                detached,
                expectation,
                epoch.receipt_sha256,
                self.settings.configuration_encryption_key,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_revocation_receipt_invalid") from None
        if revocation.request.epoch != epoch.process_epoch:
            raise conflict("managed_revocation_epoch_mismatch")
        if original.provision_claim != claim:
            raise conflict("managed_provision_claim_invalid")
        grant = await self.grants.locked(window.grant_id)
        if (
            grant is None
            or not grant.is_closed
            or grant.mode != "reserved"
            or grant.node_id != node_id
            or grant.subscription_id != subscription_id
            or grant.profile_id != window.profile_id
            or grant.generation != window.generation
            or grant.process_epoch != epoch.process_epoch
            or grant.allocated_bytes != window.allocated_bytes
        ):
            raise conflict("managed_revocation_finality_required")
        barrier = await self.barriers.by_identity(
            epoch_id, revocation.snapshot.barrier_id
        )
        if barrier is None:
            raise conflict("managed_revocation_finality_required")
        try:
            await asyncio.to_thread(
                ManagedRevocationEncoding.verify_finality,
                revocation,
                detached,
                ManagedBarrierModel.model_validate(barrier.model_dump()),
                expectation,
                self.settings.configuration_encryption_key,
            )
        except (ValueError, TypeError, KeyError):
            raise conflict("managed_revocation_finality_mismatch") from None
        existing = await self.revocations.by_window(window.id)
        result = ManagedRevocationOut(
            window_id=window.window_id,
            provision_task_id=claim.task_id,
            revocation_sha256=data.receipt.receipt_sha256,
            observed_at=revocation.observed_at,
        )
        if existing is not None:
            if (
                existing.receipt_sha256 != data.receipt.receipt_sha256
                or existing.provision_task_id != claim.task_id
            ):
                raise conflict("managed_revocation_receipt_reused")
            return result
        observed = revocation.observed_at.astimezone(UTC).replace(tzinfo=None)
        now = datetime.now(UTC).replace(tzinfo=None)
        if observed > now + timedelta(seconds=expectation.clock_skew_seconds):
            raise conflict("managed_revocation_observation_future")
        if (
            request is None
            or task is None
            or request.subscription_id != subscription_id
            or request.generation != window.generation
            or task.request_id != claim.request_id
            or task.node_id != node_id
            or task.profile_id != window.profile_id
        ):
            raise conflict("managed_revocation_task_mismatch")
        encrypted = await asyncio.to_thread(
            encrypt,
            data.original_receipt,
            self.settings.configuration_encryption_key,
        )
        await self.revocations.create(
            ManagedRevocationModel(
                window_id=window.id,
                provision_task_id=claim.task_id,
                receipt_sha256=data.receipt.receipt_sha256,
                observed_at=observed,
                encrypted_receipt=encrypted,
            )
        )
        await self.provisioning.revoke_managed(
            claim.task_id,
            ManagedRevocationEvidence(
                subscription_id=subscription_id,
                request_id=claim.request_id,
                node_id=node_id,
                core_id=core_id,
                profile_id=window.profile_id,
                generation=window.generation,
                configuration_id=revocation.window.binding.configuration_id,
                configuration_revision=(
                    revocation.window.binding.configuration_revision
                ),
                installed_revision_id=installation.runtime_revision_id,
                membership_sha256=revocation.window.membership_sha256,
                revocation_sha256=data.receipt.receipt_sha256,
                observed_at=observed,
            ),
        )
        return result
