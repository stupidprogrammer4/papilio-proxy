import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import (
    hash_sha256,
    secure_compare,
)

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.billing.wallet.app.ledger import ledger_entry
from src.modules.billing.wallet.domain.models import WalletModel
from src.modules.billing.wallet.infra.mysql import WalletRepository
from src.modules.network.configurations.infra.mysql import (
    ConfigurationRepository,
    ProfileRepository,
)
from src.modules.network.configurations.interfaces import IProfileCommand
from src.modules.network.core_runtime.app.memberships import (
    InstalledProfileEncoding,
)
from src.modules.network.core_runtime.interfaces import IInstalledProfileQuery
from src.modules.network.cores.interfaces import ICoreService
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.provisioning.app.payloads import (
    ProvisionNodeSecrets,
    ProvisionPayloadEncoding,
    ProvisionPayloadSource,
    RevokePayloadRefresh,
)
from src.modules.network.provisioning.domain.dtos import (
    ProvisionAcknowledgement,
    ProvisioningRetry,
)
from src.modules.network.provisioning.domain.models import (
    ProvisionRequestModel,
    ProvisionTaskModel,
)
from src.modules.network.provisioning.domain.results import (
    NodeClaim,
)
from src.modules.network.provisioning.infra.mysql import (
    ProvisionRequestRepository,
    ProvisionTaskRepository,
)
from src.modules.network.provisioning.infra.readers import (
    ProvisioningFactsReader,
)
from src.modules.network.usage.interfaces import IUsageQuery
from src.modules.operations.notifications.domain.dtos import (
    NotificationEvent,
    NotificationKind,
)
from src.modules.operations.notifications.interfaces import (
    INotificationCreateCommand,
)
from src.modules.sales.catalog.domain.policies import (
    FulfillmentPolicy,
    QuotaPolicy,
)
from src.modules.sales.loyalty.interfaces import IPurchaseVolumeCommand
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class ProvisioningCommand:
    def __init__(
        self,
        requests: ProvisionRequestRepository,
        tasks: ProvisionTaskRepository,
        subscriptions: SubscriptionRepository,
        profiles: ProfileRepository,
        profile_command: IProfileCommand,
        facts: ProvisioningFactsReader,
        nodes: INodeService,
        cores: ICoreService,
        wallets: WalletRepository,
        settings: PapilioSettings,
        configurations: ConfigurationRepository,
        usage: IUsageQuery,
        customers: ICustomerService,
        notifications: INotificationCreateCommand,
        volumes: IPurchaseVolumeCommand,
        installed: IInstalledProfileQuery,
    ) -> None:
        self.requests = requests
        self.tasks = tasks
        self.subscriptions = subscriptions
        self.profiles = profiles
        self.profile_command = profile_command
        self.facts = facts
        self.nodes = nodes
        self.cores = cores
        self.wallets = wallets
        self.settings = settings
        self.configurations = configurations
        self.usage = usage
        self.customers = customers
        self.notifications = notifications
        self.volumes = volumes
        self.installed = installed
        self.payload_encoding = ProvisionPayloadEncoding()

    @handle_conflicts
    @transactional
    async def queue(
        self, subscription_id: int, generation: int, policy: FulfillmentPolicy
    ) -> ProvisionRequestModel:
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        result = await self.requests.create(
            ProvisionRequestModel(
                subscription_id=subscription_id,
                generation=generation,
                policy_json=policy.model_dump_json(),
                state="queued",
                deadline_at=now + timedelta(minutes=policy.deadline_minutes),
            )
        )
        return result

    @transactional
    async def prepare(
        self, id: int, manual: bool = False
    ) -> ProvisionRequestModel:
        bridge = self.settings.core_provisioning
        locked_core_ids = None
        initial_group_id = None
        if bridge is not None and bridge.mode != "disabled":
            initial_request = await self.requests.get_by_id(id)
            if initial_request is None:
                raise _missing("provision_request", id)
            initial_subscription = await self.subscriptions.get_by_id(
                initial_request.subscription_id
            )
            if initial_subscription is None:
                raise _missing("subscription", initial_request.subscription_id)
            initial_group_id = initial_subscription.group_id
            target_scope = await self.facts.targets(
                initial_subscription.id,
                initial_group_id,
                self.settings.fulfillment.max_targets + 1,
            )
            task_cores = await self.facts.request_core_ids(
                id, self.settings.fulfillment.max_targets + 1
            )
            locked_core_ids = sorted(
                set(task_cores)
                | {target.configuration.core_id for target in target_scope}
            )
            if len(locked_core_ids) > self.settings.fulfillment.max_targets:
                raise _conflict("fulfillment_capacity", id)
            await self.installed.lock_cores(locked_core_ids)
        subscription, request = await self._locked_request(id)
        if (
            locked_core_ids is not None
            and subscription.group_id != initial_group_id
        ):
            raise _conflict("provision_targets_changed", id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        policy = FulfillmentPolicy.model_validate_json(request.policy_json)
        if (
            request.generation != subscription.renewal_count
            or request.state in {"refunded", "revoked", "attention"}
        ):
            return request
        customer = await self.customers.locked(subscription.customer_id)
        if (
            not CustomerAccessPolicy.services_available(customer)
            and request.state != "revoking"
        ):
            result = await self.requests.change(
                request,
                ProvisionRequestModel.patch(
                    checked_at=now, reason_code="customer_service_hold"
                ),
            )
            return result
        tasks = await self._tasks(request.id)
        if request.state in {"queued", "awaiting_profiles"}:
            if not policy.automatic and not manual:
                result = await self.requests.change(
                    request, ProvisionRequestModel.patch(checked_at=now)
                )
                return result
            targets = await self.facts.targets(
                subscription.id,
                subscription.group_id,
                self.settings.fulfillment.max_targets + 1,
                current=locked_core_ids is not None,
            )
            if locked_core_ids is not None and not {
                target.configuration.core_id for target in targets
            }.issubset(locked_core_ids):
                raise _conflict("provision_targets_changed", id)
            if len(targets) > self.settings.fulfillment.max_targets:
                result = await self.requests.change(
                    request,
                    ProvisionRequestModel.patch(
                        state="attention",
                        reason_code="target_capacity",
                        checked_at=now,
                    ),
                )
                return result
            if not targets:
                await self.requests.change(
                    request,
                    ProvisionRequestModel.patch(
                        state="awaiting_profiles",
                        reason_code="no_enabled_targets",
                        checked_at=now,
                    ),
                )
                result = await self._advance(subscription, request, tasks, now)
                return result
            profiles = await self.profile_command.assign_many(
                subscription.id,
                [target.configuration.id for target in targets],
            )
            if (
                policy.activation == "quorum"
                and policy.minimum_successes > len(targets)
            ):
                result = await self.requests.change(
                    request,
                    ProvisionRequestModel.patch(
                        state="attention",
                        reason_code="quorum_unreachable",
                        checked_at=now,
                    ),
                )
                return result
            by_configuration = {
                profile.configuration_id: profile for profile in profiles
            }
            sources = [
                ProvisionPayloadSource(
                    configuration_id=target.configuration.id,
                    profile_id=by_configuration[target.configuration.id].id,
                    core_id=target.configuration.core_id,
                    listen_port=target.configuration.listen_port,
                    encrypted_settings=target.configuration.encrypted_settings,
                    encrypted_credentials=by_configuration[
                        target.configuration.id
                    ].encrypted_credentials,
                    client_address=by_configuration[
                        target.configuration.id
                    ].client_address,
                )
                for target in targets
            ]
            encoded = await asyncio.to_thread(
                self.payload_encoding.encode_many,
                sources,
                self.settings.configuration_encryption_key,
            )
            by_payload = {value.configuration_id: value for value in encoded}
            rows = [
                ProvisionTaskModel(
                    configuration_revision=target.configuration.revision,
                    action="apply",
                    state="queued",
                    attempts=0,
                    request_id=request.id,
                    configuration_id=target.configuration.id,
                    profile_id=by_configuration[target.configuration.id].id,
                    node_id=target.node.id,
                    available_at=now,
                    encrypted_payload=by_payload[
                        target.configuration.id
                    ].ciphertext,
                )
                for target in targets
            ]
            await self.tasks.create_targets(rows)
            await self.requests.change(
                request,
                ProvisionRequestModel.patch(
                    state="dispatching", reason_code=None, checked_at=now
                ),
            )
            tasks = await self._tasks(request.id)
        if tasks and request.state in {"dispatching", "active", "revoking"}:
            await self._refresh_payloads(request, tasks, now)
            tasks = await self._tasks(request.id)
        result = await self._advance(subscription, request, tasks, now)
        return result

    @transactional
    async def retire(
        self,
        subscription_id: int,
        generation: int,
        completion: Literal["expire", "quota", "suspend", "cancel"],
        reason: str,
        staff_id: int | None,
    ) -> ProvisionRequestModel:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        request = await self.requests.by_generation(
            subscription_id, generation
        )
        if request is None:
            raise _missing("provision_request", subscription_id)
        if request.state == "revoked":
            return request
        if (
            request.state == "refunded"
            or request.state == "revoking"
            and request.completion != completion
            or generation != subscription.renewal_count
        ):
            raise _conflict("provision_retirement_conflict", subscription_id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if request.state != "revoking":
            await self.subscriptions.update_existing(
                subscription, SubscriptionModel.patch(status="revoking")
            )
            await self.requests.change(
                request,
                ProvisionRequestModel.patch(
                    completion=completion,
                    state="revoking",
                    cancellation_reason=reason,
                    cancelled_by_staff_id=staff_id,
                    checked_at=now,
                ),
            )
            await self.tasks.update_request_tasks(
                request.id,
                None,
                ProvisionTaskModel.patch(
                    action="revoke",
                    state="queued",
                    attempts=0,
                    claim_hash=None,
                    claim_until=None,
                    acknowledged_at=None,
                    last_outcome=None,
                    error_code=None,
                    available_at=now,
                ),
            )
        tasks = await self._tasks(request.id)
        result = await self._advance(subscription, request, tasks, now)
        return result

    @transactional
    async def resume(
        self, subscription_id: int, generation: int, reason: str, staff_id: int
    ) -> ProvisionRequestModel:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        request = await self.requests.by_generation(
            subscription_id, generation
        )
        if request is None:
            raise _missing("provision_request", subscription_id)
        if (
            request.state != "revoked"
            or request.completion != "suspend"
            or subscription.status != "pending_provision"
            or generation != subscription.renewal_count
        ):
            raise _conflict("subscription_resume_unavailable", subscription_id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        policy = FulfillmentPolicy.model_validate_json(request.policy_json)
        if subscription.activated_at is not None:
            policy.expiry_start = "purchase"
            policy.failure_action = "hold"
        tasks = await self._tasks(request.id)
        await self.requests.change(
            request,
            ProvisionRequestModel.patch(
                policy_json=policy.model_dump_json(),
                state="dispatching" if tasks else "queued",
                reason_code=None,
                deadline_at=now + timedelta(minutes=policy.deadline_minutes),
                activated_at=None,
                checked_at=now,
                retry_reason=reason,
                cancellation_reason=None,
                cancelled_by_staff_id=None,
                completion="refund",
            ),
        )
        await self.tasks.update_request_tasks(
            request.id,
            None,
            ProvisionTaskModel.patch(
                action="apply",
                state="queued",
                attempts=0,
                claim_hash=None,
                claim_until=None,
                acknowledged_at=None,
                last_outcome=None,
                error_code=None,
                available_at=now,
            ),
        )
        tasks = await self._tasks(request.id)
        await self._refresh_payloads(request, tasks, now)
        return request

    @transactional
    async def cancel(
        self,
        subscription_id: int,
        generation: int,
        reason: str,
        staff_id: int | None,
    ) -> ProvisionRequestModel:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        request = await self.requests.by_generation(
            subscription_id, generation
        )
        if request is None:
            raise _missing("provision_request", subscription_id)
        if request.state == "refunded":
            return request
        if subscription.status != "pending_provision":
            raise _conflict("subscription_not_pending", subscription_id)
        if subscription.activated_at is not None:
            raise _conflict("subscription_already_activated", subscription_id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if request.state != "revoking":
            await self.requests.change(
                request,
                ProvisionRequestModel.patch(
                    state="revoking",
                    completion="refund",
                    cancellation_reason=reason,
                    cancelled_by_staff_id=staff_id,
                    checked_at=now,
                ),
            )
            await self.tasks.update_request_tasks(
                request.id,
                None,
                ProvisionTaskModel.patch(
                    action="revoke",
                    state="queued",
                    attempts=0,
                    claim_hash=None,
                    claim_until=None,
                    acknowledged_at=None,
                    last_outcome=None,
                    error_code=None,
                    available_at=now,
                ),
            )
        tasks = await self._tasks(request.id)
        result = await self._advance(subscription, request, tasks, now)
        return result

    @transactional
    async def retry(
        self, id: int, data: ProvisioningRetry
    ) -> ProvisionRequestModel:
        subscription, request = await self._locked_request(id)
        if (
            request.state in {"refunded", "revoking"}
            or subscription.status not in {"active", "pending_provision"}
            or request.generation != subscription.renewal_count
        ):
            raise _conflict("provision_retry_unavailable", id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        policy = FulfillmentPolicy.model_validate_json(request.policy_json)
        tasks = await self._tasks(request.id)
        await self.tasks.update_request_tasks(
            request.id,
            ["queued", "leased", "failed"],
            ProvisionTaskModel.patch(
                state="queued",
                attempts=0,
                claim_hash=None,
                claim_until=None,
                last_outcome=None,
                error_code=None,
                acknowledged_at=None,
                available_at=now,
            ),
        )
        result = await self.requests.change(
            request,
            ProvisionRequestModel.patch(
                state="dispatching" if tasks else "queued",
                reason_code=None,
                retry_reason=data.reason,
                deadline_at=now + timedelta(minutes=policy.deadline_minutes),
                checked_at=None,
            ),
        )
        return result

    @transactional
    async def claim(self, code: str, key: str, task_id: int) -> NodeClaim:
        node = await self.nodes.authenticate(code, key)
        facts = await self.facts.node_task(task_id)
        if facts is None or facts.task.node_id != node.id:
            raise _missing("provision_task", task_id)
        bridge = self.settings.core_provisioning
        bridge_enabled = bridge is not None and bridge.mode != "disabled"
        if bridge_enabled:
            await self.installed.lock_core(facts.configuration.core_id)
        subscription, request = await self._locked_request(facts.request.id)
        task = await self.tasks.locked(task_id)
        assert task is not None
        configuration = await self.configurations.locked(task.configuration_id)
        if configuration is None:
            raise _missing("configuration", task.configuration_id)
        if (
            task.action == "apply"
            and task.configuration_revision != configuration.revision
        ):
            raise _conflict("provision_configuration_changed", task_id)
        customer = await self.customers.locked(subscription.customer_id)
        if (
            task.action == "apply"
            and not CustomerAccessPolicy.services_available(customer)
        ):
            raise _conflict("customer_services_disabled", subscription.id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        policy = FulfillmentPolicy.model_validate_json(request.policy_json)
        if task.action == "apply" and (
            not node.is_enabled
            or request.state not in {"dispatching", "active"}
            or subscription.status not in {"pending_provision", "active"}
            or request.generation != subscription.renewal_count
        ):
            raise _conflict("provision_not_claimable", task_id)
        if task.action == "revoke" and request.state != "revoking":
            raise _conflict("provision_not_claimable", task_id)
        if (
            task.state not in {"queued", "failed", "leased"}
            or task.available_at > now
            or (
                task.state == "leased"
                and task.claim_until is not None
                and task.claim_until > now
            )
        ):
            raise _conflict("provision_not_claimable", task_id)
        if task.attempts >= policy.max_attempts and task.action == "apply":
            raise _conflict("provision_attempts_exhausted", task_id)
        payload = await asyncio.to_thread(
            ProvisionPayloadEncoding.decode,
            task.encrypted_payload,
            self.settings.configuration_encryption_key,
        )
        if task.action == "apply" and not await asyncio.to_thread(
            ProvisionNodeSecrets.certificate_valid, payload, now
        ):
            raise _conflict("openvpn_certificate_unavailable", task.id)
        credential_digest = await asyncio.to_thread(
            InstalledProfileEncoding.credential_digest,
            ProvisionNodeSecrets.credentials(payload.credentials),
        )
        proof = None
        if bridge_enabled:
            proof = await self.installed.proof(
                configuration.core_id,
                task.profile_id,
                request.generation,
                task.configuration_revision,
                task.action,
                credential_digest,
            )
            if (
                proof.membership.configuration_id != task.configuration_id
                or proof.membership.subscription_id != subscription.id
                or proof.membership.client_address != payload.client_address
            ):
                raise _conflict("provision_runtime_pending", task.id)
        token = secrets.token_urlsafe(32)
        until = now + timedelta(seconds=policy.claim_seconds)
        await self.tasks.change(
            task,
            ProvisionTaskModel.patch(
                state="leased",
                attempts=task.attempts + 1,
                claim_hash=(await asyncio.to_thread(hash_sha256, token)),
                claim_until=until,
                installed_revision_id=proof.installed_revision_id
                if proof is not None
                else None,
                membership_sha256=proof.membership_sha256
                if proof is not None
                else None,
                ack_sha256=None,
                last_outcome=None,
                acknowledged_at=None,
            ),
        )
        expiry = (
            now + timedelta(days=subscription.duration_days)
            if subscription.duration_days is not None
            and policy.expiry_start == "activation"
            and subscription.status == "pending_provision"
            else subscription.expires_at
        )
        core = await self.cores.get(payload.core_id)
        return NodeClaim(
            credential_sha256=credential_digest,
            installed_revision_id=proof.installed_revision_id
            if proof is not None
            else None,
            membership_sha256=proof.membership_sha256
            if proof is not None
            else None,
            membership=proof.membership if proof is not None else None,
            quota_policy=QuotaPolicy.model_validate_json(
                subscription.quota_policy_json
            )
            if subscription.quota_policy_json is not None
            else self.settings.usage.policy,
            configuration_revision=task.configuration_revision,
            listen_port=payload.listen_port or configuration.listen_port,
            task_id=task.id,
            request_id=request.id,
            generation=request.generation,
            action=task.action,
            claim_token=token,
            claim_until=until.replace(tzinfo=UTC),
            core_id=payload.core_id,
            core_kind=core.kind,
            configuration_id=task.configuration_id,
            profile_id=task.profile_id,
            subscription_id=subscription.id,
            quota_bytes=subscription.quota_bytes,
            expires_at=None if expiry is None else expiry.replace(tzinfo=UTC),
            settings=ProvisionNodeSecrets.settings(payload.settings),
            credentials=ProvisionNodeSecrets.credentials(payload.credentials),
            client_address=payload.client_address,
        )

    @transactional
    async def acknowledge(
        self, code: str, key: str, task_id: int, data: ProvisionAcknowledgement
    ) -> ProvisionTaskModel:
        node = await self.nodes.authenticate(code, key)
        facts = await self.facts.node_task(task_id)
        if facts is None or facts.task.node_id != node.id:
            raise _missing("provision_task", task_id)
        bridge = self.settings.core_provisioning
        bridge_enabled = bridge is not None and bridge.mode != "disabled"
        if bridge_enabled:
            await self.installed.lock_core(facts.configuration.core_id)
        subscription, request = await self._locked_request(facts.request.id)
        task = await self.tasks.locked(task_id)
        assert task is not None
        configuration = await self.configurations.locked(task.configuration_id)
        if configuration is None:
            raise _missing("configuration", task.configuration_id)
        if (
            task.action == "apply"
            and task.configuration_revision != configuration.revision
        ):
            raise _conflict("provision_configuration_changed", task_id)
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if task.claim_hash is None or not secure_compare(
            task.claim_hash,
            (await asyncio.to_thread(hash_sha256, data.claim_token)),
        ):
            raise _conflict("provision_claim_invalid", task_id)
        ack_digest = await asyncio.to_thread(
            hash_sha256, data.model_dump_json()
        )
        if task.last_outcome is not None:
            if (
                task.last_outcome != data.outcome
                or task.error_code != data.error_code
                or (
                    task.ack_sha256 is not None
                    and task.ack_sha256 != ack_digest
                )
            ):
                raise _conflict("provision_ack_conflict", task_id)
            return task
        if (
            task.state != "leased"
            or task.claim_until is None
            or task.claim_until <= now
        ):
            raise _conflict("provision_claim_expired", task_id)
        expected = "applied" if task.action == "apply" else "revoked"
        if data.outcome not in {expected, "failed"}:
            raise _conflict("provision_ack_conflict", task_id)
        if data.outcome == "revoked" and await self.usage.has_open_profile(
            task.profile_id, request.generation
        ):
            raise _conflict("usage_final_report_required", task_id)
        if task.action == "apply" and (
            request.state not in {"dispatching", "active"}
            or request.generation != subscription.renewal_count
        ):
            raise _conflict("provision_not_claimable", task_id)
        if data.outcome == "applied" and configuration.protocol == "openvpn":
            payload = await asyncio.to_thread(
                ProvisionPayloadEncoding.decode,
                task.encrypted_payload,
                self.settings.configuration_encryption_key,
            )
            if not await asyncio.to_thread(
                ProvisionNodeSecrets.certificate_valid, payload, now
            ):
                raise _conflict("openvpn_certificate_unavailable", task.id)
        if bridge_enabled and data.outcome != "failed":
            payload = await asyncio.to_thread(
                ProvisionPayloadEncoding.decode,
                task.encrypted_payload,
                self.settings.configuration_encryption_key,
            )
            credential_digest = await asyncio.to_thread(
                InstalledProfileEncoding.credential_digest,
                ProvisionNodeSecrets.credentials(payload.credentials),
            )
            proof = await self.installed.proof(
                configuration.core_id,
                task.profile_id,
                request.generation,
                task.configuration_revision,
                task.action,
                credential_digest,
            )
            if (
                data.runtime_revision_id != task.installed_revision_id
                or data.runtime_revision_id != proof.installed_revision_id
                or data.membership_sha256 != task.membership_sha256
                or data.membership_sha256 != proof.membership_sha256
            ):
                raise _conflict("provision_runtime_proof_mismatch", task.id)
        elif not bridge_enabled and (
            data.runtime_revision_id is not None
            or data.membership_sha256 is not None
        ):
            raise _conflict("provision_runtime_proof_unexpected", task.id)
        policy = FulfillmentPolicy.model_validate_json(request.policy_json)
        await self.tasks.change(
            task,
            ProvisionTaskModel.patch(
                ack_sha256=ack_digest if bridge_enabled else None,
                state=data.outcome,
                last_outcome=data.outcome,
                acknowledged_at=now,
                error_code=data.error_code,
                available_at=now + timedelta(seconds=policy.retry_seconds),
            ),
        )
        if data.outcome == "applied":
            await self.profiles.mark_applied(
                task.profile_id,
                request.generation,
                task.configuration_revision,
            )
        elif data.outcome == "revoked":
            await self.profiles.mark_applied(task.profile_id, None, None)
        tasks = await self._tasks(request.id)
        await self._advance(subscription, request, tasks, now)
        return task

    async def _locked_request(
        self, id: int
    ) -> tuple[SubscriptionModel, ProvisionRequestModel]:
        initial = await self.requests.get_by_id(id)
        if initial is None:
            raise _missing("provision_request", id)
        subscription = await self.subscriptions.locked(initial.subscription_id)
        if subscription is None:
            raise _missing("subscription", initial.subscription_id)
        request = await self.requests.locked(id)
        assert request is not None
        return subscription, request

    async def _refresh_payloads(
        self,
        request: ProvisionRequestModel,
        tasks: list[ProvisionTaskModel],
        now: datetime,
    ) -> None:
        configurations = await self.configurations.locked_many(
            [task.configuration_id for task in tasks]
        )
        by_id = {
            configuration.id: configuration for configuration in configurations
        }
        changed = [
            task
            for task in tasks
            if task.configuration_revision
            != by_id[task.configuration_id].revision
        ]
        if not changed:
            return
        changed_apply = [task for task in changed if task.action == "apply"]
        changed_revoke = [task for task in changed if task.action == "revoke"]
        profiles = (
            await self.profiles.selected(
                [task.profile_id for task in changed_apply]
            )
            if changed_apply
            else []
        )
        by_profile = {profile.id: profile for profile in profiles}
        apply_sources = [
            ProvisionPayloadSource(
                configuration_id=task.configuration_id,
                profile_id=task.profile_id,
                core_id=by_id[task.configuration_id].core_id,
                listen_port=by_id[task.configuration_id].listen_port,
                encrypted_settings=by_id[
                    task.configuration_id
                ].encrypted_settings,
                encrypted_credentials=by_profile[
                    task.profile_id
                ].encrypted_credentials,
                client_address=by_profile[task.profile_id].client_address,
            )
            for task in changed_apply
        ]
        revoke_sources = [
            RevokePayloadRefresh(
                configuration_id=task.configuration_id,
                profile_id=task.profile_id,
                listen_port=by_id[task.configuration_id].listen_port,
                encrypted_settings=by_id[
                    task.configuration_id
                ].encrypted_settings,
                original_encrypted_payload=task.encrypted_payload,
            )
            for task in changed_revoke
        ]
        applied, revoked = await asyncio.gather(
            asyncio.to_thread(
                self.payload_encoding.encode_many,
                apply_sources,
                self.settings.configuration_encryption_key,
            ),
            asyncio.to_thread(
                self.payload_encoding.refresh_revocations,
                revoke_sources,
                self.settings.configuration_encryption_key,
            ),
        )
        by_payload = {
            value.profile_id: value for value in (*applied, *revoked)
        }
        rows = [
            ProvisionTaskModel.patch(
                id=task.id,
                configuration_revision=by_id[task.configuration_id].revision,
                encrypted_payload=by_payload[task.profile_id].ciphertext,
                state="queued",
                attempts=0,
                claim_hash=None,
                claim_until=None,
                last_outcome=None,
                acknowledged_at=None,
                error_code=None,
                available_at=now,
            )
            for task in changed
        ]
        await self.tasks.replace_payloads(rows)
        await self.profiles.invalidate_many(
            [task.profile_id for task in changed_apply]
        )

    async def _tasks(self, request_id: int) -> list[ProvisionTaskModel]:
        capacity = self.settings.fulfillment.max_targets
        rows = await self.tasks.for_request(request_id, capacity + 1)
        if len(rows) > capacity:
            raise _conflict("fulfillment_capacity", request_id)
        return rows

    async def _advance(
        self,
        subscription: SubscriptionModel,
        request: ProvisionRequestModel,
        tasks: list[ProvisionTaskModel],
        now: datetime,
    ) -> ProvisionRequestModel:
        policy = FulfillmentPolicy.model_validate_json(request.policy_json)
        customer = await self.customers.locked(subscription.customer_id)
        if request.state == "revoking":
            if all(task.state == "revoked" for task in tasks):
                if request.completion != "refund":
                    status = {
                        "expire": "expired",
                        "quota": "exhausted",
                        "suspend": "suspended",
                        "cancel": "cancelled",
                    }[request.completion]
                    await self.subscriptions.update_existing(
                        subscription,
                        SubscriptionModel.patch(
                            status=status,
                            auto_renew=False
                            if request.completion == "cancel"
                            else subscription.auto_renew,
                        ),
                    )
                    result = await self.requests.change(
                        request,
                        ProvisionRequestModel.patch(
                            state="revoked", checked_at=now
                        ),
                    )
                    return result
                if subscription.price_rial > 0:
                    wallet = await self.wallets.locked_for_customer(
                        WalletModel(
                            customer_id=subscription.payer_customer_id
                            or subscription.customer_id,
                            balance_rial=0,
                        )
                    )
                    await self.wallets.record(
                        wallet,
                        ledger_entry(
                            wallet,
                            subscription.price_rial,
                            f"provision_refund:{subscription.id}:{request.generation}",
                            "provision_refund",
                        ),
                    )
                await self.volumes.reverse(subscription.id, request.generation)
                await self.subscriptions.update_existing(
                    subscription,
                    SubscriptionModel.patch(
                        status="failed",
                        auto_renew=False,
                        failure_reason=request.cancellation_reason
                        or "راه‌اندازی ناموفق",
                        failed_by_staff_id=request.cancelled_by_staff_id,
                    ),
                )
                result = await self.requests.change(
                    request,
                    ProvisionRequestModel.patch(
                        state="refunded", checked_at=now
                    ),
                )
                return result
            result = await self.requests.change(
                request, ProvisionRequestModel.patch(checked_at=now)
            )
            return result
        if not CustomerAccessPolicy.services_available(customer):
            result = await self.requests.change(
                request,
                ProvisionRequestModel.patch(
                    checked_at=now, reason_code="customer_service_hold"
                ),
            )
            return result
        successes = sum(task.state == "applied" for task in tasks)
        needed = (
            len(tasks)
            if policy.activation == "all"
            else policy.minimum_successes
            if policy.activation == "quorum"
            else 1
        )
        if tasks and successes >= needed and request.activated_at is None:
            expiry = (
                now + timedelta(days=subscription.duration_days)
                if subscription.duration_days is not None
                and policy.expiry_start == "activation"
                else subscription.expires_at
            )
            if expiry is not None and expiry <= now:
                await self.requests.change(
                    request,
                    ProvisionRequestModel.patch(
                        state="attention",
                        reason_code="expired_before_activation",
                        checked_at=now,
                    ),
                )
                return request
            await self.subscriptions.update_existing(
                subscription,
                SubscriptionModel.patch(
                    status="active",
                    expires_at=expiry,
                    activated_at=subscription.activated_at or now,
                ),
            )
            await self.profile_command.subscription_url(subscription.id, False)
            await self.requests.change(
                request,
                ProvisionRequestModel.patch(
                    state="active",
                    activated_at=now,
                    reason_code=None,
                    checked_at=now,
                ),
            )
            await self.notifications.enqueue(
                subscription.customer_id,
                NotificationEvent(
                    event_key=f"activation:{request.id}",
                    kind=NotificationKind.SUBSCRIPTION_ACTIVE,
                    status="فعال",
                    record_id=subscription.id,
                ),
            )
        outstanding = [task for task in tasks if task.state != "applied"]
        exhausted = bool(outstanding) and all(
            task.attempts >= policy.max_attempts
            and (
                task.claim_until is None
                or task.claim_until <= now
                or task.last_outcome is not None
            )
            for task in outstanding
        )
        timed_out = request.deadline_at <= now
        if (exhausted or timed_out) and request.activated_at is None:
            if policy.failure_action == "refund_wallet":
                await self.requests.change(
                    request,
                    ProvisionRequestModel.patch(
                        state="revoking",
                        completion="refund",
                        reason_code="provision_timeout",
                        cancellation_reason="مهلت راه‌اندازی پایان یافته است.",
                        checked_at=now,
                    ),
                )
                await self.tasks.update_request_tasks(
                    request.id,
                    None,
                    ProvisionTaskModel.patch(
                        action="revoke",
                        state="queued",
                        attempts=0,
                        claim_hash=None,
                        claim_until=None,
                        acknowledged_at=None,
                        last_outcome=None,
                        error_code=None,
                        available_at=now,
                    ),
                )
                if not tasks:
                    if subscription.price_rial > 0:
                        wallet = await self.wallets.locked_for_customer(
                            WalletModel(
                                customer_id=subscription.payer_customer_id
                                or subscription.customer_id,
                                balance_rial=0,
                            )
                        )
                        await self.wallets.record(
                            wallet,
                            ledger_entry(
                                wallet,
                                subscription.price_rial,
                                f"provision_refund:{subscription.id}:{request.generation}",
                                "provision_refund",
                            ),
                        )
                    await self.volumes.reverse(
                        subscription.id, request.generation
                    )
                    await self.subscriptions.update_existing(
                        subscription,
                        SubscriptionModel.patch(
                            status="failed",
                            auto_renew=False,
                            failure_reason=request.cancellation_reason,
                        ),
                    )
                    await self.requests.change(
                        request, ProvisionRequestModel.patch(state="refunded")
                    )
            else:
                await self.requests.change(
                    request,
                    ProvisionRequestModel.patch(
                        state="attention",
                        reason_code="provision_timeout",
                        checked_at=now,
                    ),
                )
        else:
            await self.requests.change(
                request, ProvisionRequestModel.patch(checked_at=now)
            )
        return request


def _missing(entity: str, id: int) -> NotFoundException:
    return NotFoundException(
        message="رکورد راه‌اندازی پیدا نشد.",
        message_code=f"{entity}_not_found",
        entity=entity,
        identifier="id",
        identifier_value=id,
    )


def _conflict(code: str, id: int) -> ConflictException:
    return ConflictException(
        message="وضعیت عملیات راه‌اندازی با درخواست سازگار نیست.",
        message_code=code,
        unique_dict={"id": id},
    )
