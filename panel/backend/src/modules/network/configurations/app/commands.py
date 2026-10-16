import asyncio
import secrets
from datetime import UTC, datetime
from ipaddress import ip_interface, ip_network

import anyio
from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.security.crypto import decrypt, encrypt, hash_sha256

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.configurations.app.allocation import (
    ProfileAllocation,
    ProfileAllocationSource,
)
from src.modules.network.configurations.app.exports import (
    ConfigurationCredentials,
    ProtocolExporter,
)
from src.modules.network.configurations.app.server_json import (
    ServerJsonComposition,
)
from src.modules.network.configurations.domain.dtos import (
    ProfileCreate,
    ProfileSearch,
    WireguardOptions,
)
from src.modules.network.configurations.domain.models import (
    ProfileModel,
    SubscriptionLinkModel,
)
from src.modules.network.configurations.domain.openvpn import OpenVpnOptions
from src.modules.network.configurations.domain.results import (
    ClientCredentials,
    ConfigurationDownload,
    ConnectionEndpoint,
    ProfileAppliedUpdate,
    SubscriptionLinkMaterial,
    SubscriptionTokenInput,
    SubscriptionURL,
)
from src.modules.network.configurations.infra.mysql import (
    ConfigurationRepository,
    ProfileRepository,
    SubscriptionLinkRepository,
)
from src.modules.network.configurations.interfaces import IConfigurationCommand
from src.modules.network.nodes.interfaces import INodeService
from src.modules.sales.subscriptions.infra.mysql import SubscriptionRepository
from src.modules.sales.subscriptions.interfaces import (
    ISubscriptionBatchService,
)


class ProfileCommand:
    def __init__(
        self,
        profiles: ProfileRepository,
        subscriptions: SubscriptionRepository,
        links: SubscriptionLinkRepository,
        configurations: IConfigurationCommand,
        nodes: INodeService,
        settings: PapilioSettings,
        configuration_repo: ConfigurationRepository,
        subscription_batches: ISubscriptionBatchService,
    ) -> None:
        self.profiles = profiles
        self.subscriptions = subscriptions
        self.links = links
        self.configurations = configurations
        self.nodes = nodes
        self.config = settings
        self.configuration_repo = configuration_repo
        self.subscription_batches = subscription_batches
        self.credentials = ConfigurationCredentials()
        self.exporter = ProtocolExporter()
        self.allocation = ProfileAllocation(self.credentials)

    @handle_conflicts
    @transactional
    async def assign(
        self, configuration_id: int, data: ProfileCreate
    ) -> ProfileModel:
        subscription = await self.subscriptions.locked(data.subscription_id)
        if subscription is None:
            raise _missing("subscription", data.subscription_id)
        if subscription.status not in {"pending_provision", "active"} or (
            subscription.status == "active"
            and subscription.expires_at is not None
            and subscription.expires_at
            <= datetime.now(UTC).replace(tzinfo=None)
        ):
            raise ConflictException(
                message="این اشتراک قابل راه‌اندازی نیست.",
                message_code="subscription_not_provisionable",
                unique_dict={"subscription_id": subscription.id},
            )
        configuration = await self.configuration_repo.locked(configuration_id)
        if configuration is None:
            raise _missing("configuration", configuration_id)
        settings = await self.configurations.settings(configuration_id)
        ServerJsonComposition.require_assignable(settings)
        existing = await self.profiles.by_subscription(
            configuration_id, subscription.id
        )
        if existing is not None:
            if existing.client_address != data.client_address:
                raise ConflictException(
                    message="این اشتراک قبلاً با نشانی دیگری ثبت شده است.",
                    message_code="profile_address_changed",
                    unique_dict={"subscription_id": subscription.id},
                )
            return existing
        options = settings.options
        if isinstance(options, WireguardOptions):
            if data.client_address is None:
                raise ConflictException(
                    message="نشانی اختصاصی کاربر لازم است.",
                    message_code="wireguard_address_required",
                    unique_dict={"configuration_id": configuration_id},
                )
            address = ip_interface(data.client_address)
            pool = ip_network(options.client_subnet)
            if (
                address.network.prefixlen != address.max_prefixlen
                or address.ip not in pool
                or address.ip
                in {
                    pool.network_address,
                    pool.broadcast_address,
                    ip_interface(options.server_address).ip,
                }
            ):
                raise ConflictException(
                    message="نشانی کاربر داخل محدودهٔ نود نیست.",
                    message_code="wireguard_address_invalid",
                    unique_dict={"configuration_id": configuration_id},
                )
        elif data.client_address is not None:
            raise ConflictException(
                message="این پروتکل به نشانی تونل نیاز ندارد.",
                message_code="profile_address_unexpected",
                unique_dict={"configuration_id": configuration_id},
            )
        credentials = await asyncio.to_thread(
            self.credentials.client, options, settings
        )
        result = await self.profiles.create(
            ProfileModel(
                configuration_id=configuration_id,
                subscription_id=subscription.id,
                client_address=data.client_address,
                encrypted_credentials=(
                    await asyncio.to_thread(
                        encrypt,
                        credentials.model_dump_json(),
                        self.config.configuration_encryption_key,
                    )
                ),
            )
        )
        return result

    @handle_conflicts
    @transactional
    async def assign_many(
        self, subscription_id: int, configuration_ids: list[int]
    ) -> list[ProfileModel]:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        capacity = self.config.fulfillment.max_targets
        if (
            subscription.status != "pending_provision"
            or not configuration_ids
            or len(configuration_ids) > capacity
            or len(set(configuration_ids)) != len(configuration_ids)
        ):
            raise ConflictException(
                message="درخواست تخصیص ورودی معتبر نیست.",
                message_code="provision_targets_invalid",
                unique_dict={"subscription_id": subscription_id},
            )
        configurations = await self.configuration_repo.locked_many(
            configuration_ids
        )
        if len(configurations) != len(configuration_ids):
            raise _missing("configuration", subscription_id)
        address_capacity = self.config.fulfillment.max_address_scan
        own_profiles = await self.profiles.assigned_targets(
            subscription_id, configuration_ids
        )
        wireguard_ids = [
            configuration.id
            for configuration in configurations
            if configuration.protocol == "wireguard"
        ]
        existing = (
            await self.profiles.for_configurations(
                wireguard_ids, address_capacity + 1
            )
            if wireguard_ids
            else []
        )
        if len(existing) > address_capacity:
            raise ConflictException(
                message="ظرفیت بررسی آدرس‌ها کافی نیست.",
                message_code="profile_allocation_capacity",
                unique_dict={"subscription_id": subscription_id},
            )
        assigned_ids = {profile.configuration_id for profile in own_profiles}
        sources = [
            ProfileAllocationSource(
                configuration.id,
                configuration.encrypted_settings,
                tuple(
                    profile.client_address
                    for profile in existing
                    if profile.configuration_id == configuration.id
                    and profile.client_address is not None
                ),
            )
            for configuration in configurations
            if configuration.id not in assigned_ids
        ]
        rows = await asyncio.to_thread(
            self.allocation.allocate_many,
            subscription_id,
            sources,
            address_capacity,
            self.config.configuration_encryption_key,
        )
        await self.profiles.create_many(rows)
        result = await self.profiles.assigned_targets(
            subscription_id, configuration_ids
        )
        return result

    async def search(
        self, configuration_id: int, data: ProfileSearch
    ) -> ServicePage[ProfileModel]:
        await self.configurations.get(configuration_id)
        limit = page_size(self.config, data.per_page)
        result = await self.profiles.page(
            configuration_id, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)

    async def client(self, id: int) -> ConfigurationDownload:
        profile = await self.profiles.get_by_id(id)
        if profile is None:
            raise _missing("profile", id)
        configuration = await self.configurations.get(profile.configuration_id)
        node = await self.nodes.get(configuration.node_id)
        settings = await self.configurations.settings(configuration.id)
        credentials = ClientCredentials.model_validate_json(
            (
                await asyncio.to_thread(
                    decrypt,
                    profile.encrypted_credentials,
                    self.config.configuration_encryption_key,
                )
            )
        )
        try:
            content = await asyncio.to_thread(
                self.exporter.client,
                ConnectionEndpoint(
                    configuration.id,
                    node.public_host,
                    configuration.listen_port,
                ),
                settings,
                credentials,
                profile.client_address,
                configuration.label,
            )
        except ValueError as error:
            if not isinstance(settings.options, OpenVpnOptions):
                raise
            raise ConflictException(
                message="گواهی OpenVPN معتبر نیست؛ ورودی را بازبینی کنید.",
                message_code="openvpn_certificate_unavailable",
                unique_dict={"profile_id": id},
            ) from error
        extension = (
            "ovpn"
            if isinstance(settings.options, OpenVpnOptions)
            else "conf"
            if isinstance(settings.options, WireguardOptions)
            else "txt"
        )
        return ConfigurationDownload(
            f"profile-{id}.{extension}", content, "text/plain"
        )

    @handle_conflicts
    @transactional
    async def subscription_url(
        self, subscription_id: int, rotate: bool
    ) -> str:
        subscription = await self.subscriptions.locked(subscription_id)
        if subscription is None:
            raise _missing("subscription", subscription_id)
        link = await self.links.by_subscription(subscription_id)
        if link is None or rotate:
            token = secrets.token_urlsafe(32)
            changes = SubscriptionLinkModel(
                subscription_id=subscription_id,
                token_hash=(await asyncio.to_thread(hash_sha256, token)),
                encrypted_token=(
                    await asyncio.to_thread(
                        encrypt,
                        token,
                        self.config.configuration_encryption_key,
                    )
                ),
            )
            if link is None:
                await self.links.create(changes)
            else:
                await self.links.replace(link, changes)
        else:
            token = await asyncio.to_thread(
                decrypt,
                link.encrypted_token,
                self.config.configuration_encryption_key,
            )
        return (
            f"{self.config.public.subscription_origin.rstrip('/')}/s/{token}"
        )

    @handle_conflicts
    @transactional
    async def subscription_urls_many(
        self, subscription_ids: list[int], rotate: bool
    ) -> list[SubscriptionURL]:
        selected = sorted(set(subscription_ids))
        capacity = self.config.fulfillment.max_targets
        if (
            not selected
            or len(selected) != len(subscription_ids)
            or len(selected) > capacity
        ):
            raise ConflictException(
                message="درخواست پیوند اشتراک معتبر نیست.",
                message_code="subscription_link_batch_invalid",
                unique_dict={},
            )
        subscriptions = await self.subscription_batches.locked_many(selected)
        if {item.id for item in subscriptions} != set(selected):
            raise _missing("subscription", selected[0])
        links = await self.links.by_subscriptions_many(selected)
        links_by_subscription = {item.subscription_id: item for item in links}
        token_inputs = tuple(
            SubscriptionTokenInput(
                subscription_id=subscription_id,
                token=secrets.token_urlsafe(32),
            )
            for subscription_id in selected
            if rotate or subscription_id not in links_by_subscription
        )
        materials = await anyio.to_thread.run_sync(
            self.encode_subscription_links,
            token_inputs,
            self.config.configuration_encryption_key,
        )
        materials_by_subscription = {
            item.subscription_id: item for item in materials
        }
        creates = [
            SubscriptionLinkModel(
                subscription_id=item.subscription_id,
                token_hash=item.token_hash,
                encrypted_token=item.encrypted_token,
            )
            for item in materials
            if item.subscription_id not in links_by_subscription
        ]
        replacements = [
            SubscriptionLinkModel.patch(
                id=links_by_subscription[item.subscription_id].id,
                token_hash=item.token_hash,
                encrypted_token=item.encrypted_token,
            )
            for item in materials
            if item.subscription_id in links_by_subscription
        ]
        await self.links.create_many(creates)
        await self.links.replace_many(replacements)
        reusable = tuple(
            SubscriptionLinkMaterial(
                subscription_id=link.subscription_id,
                token="",
                token_hash=link.token_hash,
                encrypted_token=link.encrypted_token,
            )
            for link in links
            if not rotate
            and link.subscription_id not in materials_by_subscription
        )
        tokens = await anyio.to_thread.run_sync(
            self.decode_subscription_links,
            reusable,
            self.config.configuration_encryption_key,
        )
        tokens_by_subscription = {
            item.subscription_id: item.token for item in tokens
        }
        tokens_by_subscription.update(
            {
                subscription_id: material.token
                for subscription_id, material in (
                    materials_by_subscription.items()
                )
            }
        )
        origin = self.config.public.subscription_origin.rstrip("/")
        result = [
            SubscriptionURL(
                subscription_id=subscription_id,
                url=f"{origin}/s/{tokens_by_subscription[subscription_id]}",
            )
            for subscription_id in selected
        ]
        return result

    async def mark_applied_many(
        self, updates: list[ProfileAppliedUpdate]
    ) -> None:
        await self.profiles.mark_applied_many(updates)

    @staticmethod
    def encode_subscription_links(
        tokens: tuple[SubscriptionTokenInput, ...], key: str
    ) -> tuple[SubscriptionLinkMaterial, ...]:
        return tuple(
            SubscriptionLinkMaterial(
                subscription_id=item.subscription_id,
                token=item.token,
                token_hash=hash_sha256(item.token),
                encrypted_token=encrypt(item.token, key),
            )
            for item in tokens
        )

    @staticmethod
    def decode_subscription_links(
        links: tuple[SubscriptionLinkMaterial, ...], key: str
    ) -> tuple[SubscriptionTokenInput, ...]:
        return tuple(
            SubscriptionTokenInput(
                subscription_id=item.subscription_id,
                token=decrypt(item.encrypted_token, key),
            )
            for item in links
        )


def _missing(entity: str, id: int) -> NotFoundException:
    return NotFoundException(
        message="رکورد پیدا نشد.",
        message_code=f"{entity}_not_found",
        entity=entity,
        identifier="id",
        identifier_value=id,
    )
