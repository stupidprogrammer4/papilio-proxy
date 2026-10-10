import asyncio
from datetime import UTC, datetime, timedelta

from papilio.errors.exceptions import (
    ConflictException,
    NotFoundException,
    UnAuthorizedException,
)
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import hash_sha256, secure_compare

from src.config.settings import PapilioSettings
from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.accounts.customers.interfaces import ICustomerService
from src.modules.network.core_runtime.interfaces import IInstalledUsageQuery
from src.modules.network.nodes.interfaces import INodeService
from src.modules.network.usage.domain.dtos import UsageAllocation, UsageReport
from src.modules.network.usage.domain.models import (
    UsageEventModel,
    UsageGrantModel,
)
from src.modules.network.usage.infra.mysql import (
    UsageEventRepository,
    UsageGrantRepository,
)
from src.modules.network.usage.infra.readers import UsageFactsReader
from src.modules.sales.catalog.domain.policies import QuotaPolicy
from src.modules.sales.subscriptions.domain.models import SubscriptionModel
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository


class UsageCommand:
    def __init__(
        self,
        grants: UsageGrantRepository,
        events: UsageEventRepository,
        facts: UsageFactsReader,
        subscriptions: SubscriptionRepository,
        nodes: INodeService,
        settings: PapilioSettings,
        customers: ICustomerService,
        installed: IInstalledUsageQuery,
    ) -> None:
        self.grants = grants
        self.events = events
        self.facts = facts
        self.subscriptions = subscriptions
        self.nodes = nodes
        self.settings = settings
        self.customers = customers
        self.installed = installed

    @handle_conflicts
    @transactional
    async def allocate(
        self, code: str, key: str, data: UsageAllocation
    ) -> UsageGrantModel:
        node = await self.nodes.authenticate(code, key)
        initial = await self.facts.assignment(data.profile_id, node.id)
        if initial is None:
            raise _missing("profile", data.profile_id)
        subscription_id = initial.profile.subscription_id
        core_id = initial.configuration.core_id
        hint = await self.subscriptions.get_by_id(subscription_id)
        if hint is None:
            raise _missing("subscription", subscription_id)
        customer_id = hint.customer_id
        customer = await self.customers.locked(customer_id)
        node = await self.nodes.locked(node.id)
        digest = await asyncio.to_thread(hash_sha256, key)
        if node.code != code or not secure_compare(
            digest, node.agent_key_hash
        ):
            raise UnAuthorizedException(
                message="Node authorization changed while waiting.",
                message_code="node_unauthorized",
            )
        if data.installed_revision_id is not None:
            await self.installed.lock_core(core_id)
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        if subscription.customer_id != customer_id:
            raise _conflict(
                "usage_subscription_owner_changed", subscription.id
            )
        facts = await self.facts.assignment(
            data.profile_id, node.id, lock=True
        )
        if facts is None:
            raise _missing("profile", data.profile_id)
        if (
            facts.profile.subscription_id != subscription_id
            or facts.configuration.core_id != core_id
        ):
            raise _conflict("usage_assignment_changed", data.profile_id)
        if not CustomerAccessPolicy.services_available(customer):
            raise _conflict("customer_services_disabled", subscription.id)
        existing = await self.grants.allocation(
            data.profile_id, data.generation, data.request_key
        )
        if existing is not None:
            if (
                existing.allocated_bytes != data.requested_bytes
                or existing.installed_revision_id != data.installed_revision_id
                or existing.usage_sha256 != data.usage_sha256
                or existing.process_epoch != data.process_epoch
            ):
                raise _conflict("usage_allocation_reused", existing.id)
            return existing
        if (
            self.installed.required(facts.configuration.core_id)
            and data.installed_revision_id is None
        ):
            raise _conflict("runtime_usage_proof_required", data.profile_id)
        await self.installed.allocation_guard(facts.configuration.core_id)
        if data.installed_revision_id is not None:
            assert (
                data.usage_sha256 is not None
                and data.process_epoch is not None
            )
            await self.installed.proof(
                facts.configuration.core_id,
                node.id,
                data.profile_id,
                subscription.id,
                data.generation,
                facts.configuration.revision,
                data.installed_revision_id,
                data.usage_sha256,
                data.process_epoch,
            )
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        if (
            not node.is_enabled
            or subscription.status != "active"
            or (
                subscription.expires_at is not None
                and subscription.expires_at <= now
            )
            or data.generation != subscription.renewal_count
            or subscription.provisioning_managed
            and (
                facts.profile.applied_generation != data.generation
                or facts.profile.applied_revision
                != facts.configuration.revision
            )
        ):
            raise _conflict("usage_entitlement_inactive", subscription.id)
        policy = (
            QuotaPolicy.model_validate_json(subscription.quota_policy_json)
            if subscription.quota_policy_json is not None
            else self.settings.usage.policy
        )
        if data.requested_bytes > policy.grant_bytes:
            raise _conflict("usage_grant_capacity", data.profile_id)
        if await self.facts.has_open_profile(data.profile_id, data.generation):
            raise _conflict("usage_final_report_required", data.profile_id)
        reserved = await self.facts.reserved_bytes(
            subscription.id, data.generation, ["reserved"]
        )
        available = (
            None
            if subscription.quota_bytes is None
            else max(
                subscription.quota_bytes - subscription.used_bytes - reserved,
                0,
            )
        )
        if available is not None and (
            available <= 0
            or policy.mode == "reserved"
            and data.requested_bytes > available
        ):
            raise _conflict("usage_quota_unavailable", subscription.id)
        result = await self.grants.create(
            UsageGrantModel(
                subscription_id=subscription.id,
                profile_id=data.profile_id,
                node_id=node.id,
                generation=data.generation,
                configuration_revision=facts.configuration.revision,
                request_key=data.request_key,
                mode=policy.mode,
                allocated_bytes=data.requested_bytes,
                upload_bytes=0,
                download_bytes=0,
                sequence=0,
                is_closed=False,
                valid_until=min(
                    now + timedelta(seconds=policy.grant_seconds),
                    subscription.expires_at
                    or now + timedelta(seconds=policy.grant_seconds),
                ),
                installed_revision_id=data.installed_revision_id,
                usage_sha256=data.usage_sha256,
                process_epoch=data.process_epoch,
            )
        )
        return result

    @handle_conflicts
    @transactional
    async def report(
        self, code: str, key: str, grant_id: int, data: UsageReport
    ) -> UsageEventModel:
        node = await self.nodes.authenticate(code, key)
        node = await self.nodes.locked(node.id)
        node_digest = await asyncio.to_thread(hash_sha256, key)
        if node.code != code or not secure_compare(
            node_digest, node.agent_key_hash
        ):
            raise UnAuthorizedException(
                message="Node authorization changed while waiting.",
                message_code="node_unauthorized",
            )
        initial = await self.grants.get_by_id(grant_id)
        if initial is None or initial.node_id != node.id:
            raise _missing("usage_grant", grant_id)
        subscription = await self.subscriptions.locked(initial.subscription_id)
        if subscription is None:
            raise _missing("subscription", initial.subscription_id)
        grant = await self.grants.locked(grant_id)
        assert grant is not None
        managed_window_id = await self.facts.managed_window_id(grant.id)
        if managed_window_id is not None:
            raise _conflict("managed_usage_finality_required", grant.id)
        if data.process_epoch != grant.process_epoch:
            raise _conflict("usage_process_epoch_mismatch", grant.id)
        digest = await asyncio.to_thread(
            hash_sha256,
            str(grant_id)
            + ":"
            + data.model_dump_json(
                exclude={"process_epoch"}
                if data.process_epoch is None
                else set()
            ),
        )
        existing = await self.events.by_identity(node.id, data.event_id)
        if existing is not None:
            if not secure_compare(existing.payload_hash, digest):
                raise _conflict("usage_event_reused", grant_id)
            return existing
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        sampled = data.sampled_at.astimezone(UTC).replace(
            tzinfo=None, microsecond=0
        )
        policy = (
            QuotaPolicy.model_validate_json(subscription.quota_policy_json)
            if subscription.quota_policy_json is not None
            else self.settings.usage.policy
        )
        if sampled > now + timedelta(
            seconds=policy.report_future_seconds
        ) or sampled < now - timedelta(seconds=policy.report_max_age_seconds):
            raise _conflict("usage_sample_time", grant_id)
        if (
            grant.is_closed
            or data.sequence <= grant.sequence
            or data.upload_bytes < grant.upload_bytes
            or data.download_bytes < grant.download_bytes
            or grant.sampled_at is not None
            and sampled < grant.sampled_at
        ):
            raise _conflict("usage_counter_conflict", grant_id)
        upload = data.upload_bytes - grant.upload_bytes
        download = data.download_bytes - grant.download_bytes
        delta = upload + download
        if (
            delta > self.settings.usage.max_report_delta_bytes
            or subscription.used_bytes + delta > 2**63 - 1
        ):
            raise _conflict("usage_report_capacity", grant_id)
        event = await self.events.create(
            UsageEventModel(
                grant_id=grant.id,
                subscription_id=subscription.id,
                node_id=node.id,
                generation=grant.generation,
                event_id=data.event_id,
                payload_hash=digest,
                sequence=data.sequence,
                upload_bytes=data.upload_bytes,
                download_bytes=data.download_bytes,
                delta_upload_bytes=upload,
                delta_download_bytes=download,
                delta_bytes=delta,
                final=data.final,
                sampled_at=sampled,
            )
        )
        await self.grants.change(
            grant,
            UsageGrantModel.patch(
                upload_bytes=data.upload_bytes,
                download_bytes=data.download_bytes,
                sequence=data.sequence,
                sampled_at=sampled,
                is_closed=data.final,
            ),
        )
        if grant.generation == subscription.renewal_count:
            await self.subscriptions.update_existing(
                subscription,
                SubscriptionModel.patch(
                    used_bytes=subscription.used_bytes + delta
                ),
            )
        return event


def _missing(entity: str, id: int) -> NotFoundException:
    return NotFoundException(
        message="رکورد مصرف پیدا نشد.",
        message_code=f"{entity}_not_found",
        entity=entity,
        identifier="id",
        identifier_value=id,
    )


def _conflict(code: str, id: int) -> ConflictException:
    return ConflictException(
        message="درخواست سهمیه یا گزارش مصرف با وضعیت ثبت‌شده سازگار نیست.",
        message_code=code,
        unique_dict={"id": id},
    )
