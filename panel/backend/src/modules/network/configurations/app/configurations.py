import asyncio
from ipaddress import ip_interface, ip_network

from papilio.errors.exceptions import ConflictException, NotFoundException
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, page_size, service_page
from src.config.settings import PapilioSettings
from src.modules.network.configurations.app.export_inputs import (
    ServerExportInputs,
)
from src.modules.network.configurations.app.exports import (
    ConfigurationCredentials,
)
from src.modules.network.configurations.app.openvpn_policy import (
    OpenVpnConfigurationPolicy,
)
from src.modules.network.configurations.app.server_batch import (
    ConfigurationServerBatchRenderer,
)
from src.modules.network.configurations.app.server_exports import (
    ServerConfigurationRenderer,
)
from src.modules.network.configurations.app.server_json import (
    ServerJsonComposition,
)
from src.modules.network.configurations.domain.dtos import (
    ConfigurationCreate,
    ConfigurationSearch,
    ConfigurationUpdate,
    WireguardOptions,
)
from src.modules.network.configurations.domain.models import (
    ConfigurationJsonRevisionModel,
    ConfigurationModel,
    InboundPortModel,
    OpenVpnSocketModel,
)
from src.modules.network.configurations.domain.openvpn import (
    OpenVpnCapacity,
    OpenVpnOptions,
)
from src.modules.network.configurations.domain.results import (
    ConfigurationDownload,
    ConfigurationServerExport,
    ConnectionEndpoint,
    StoredSettings,
)
from src.modules.network.configurations.domain.server_json import (
    ServerJsonDocument,
    ServerJsonHistorySearch,
    ServerJsonRestore,
    ServerJsonRevision,
    ServerJsonState,
    ServerJsonUpdate,
)
from src.modules.network.configurations.infra.mysql import (
    ConfigurationJsonRevisionRepository,
    ConfigurationRepository,
    InboundPortRepository,
    ProfileRepository,
)
from src.modules.network.configurations.infra.readers import (
    ConfigurationFactsReader,
)
from src.modules.network.configurations.interfaces import (
    IOpenVpnSocketService,
)
from src.modules.network.cores.interfaces import ICoreService
from src.modules.network.nodes.interfaces import INodeService


class ConfigurationCommand:
    def __init__(
        self,
        repo: ConfigurationRepository,
        nodes: INodeService,
        ports: InboundPortRepository,
        cores: ICoreService,
        reader: ConfigurationFactsReader,
        settings: PapilioSettings,
        management: IOpenVpnSocketService,
        json_revisions: ConfigurationJsonRevisionRepository,
        profiles: ProfileRepository,
    ) -> None:
        self.repo = repo
        self.nodes = nodes
        self.ports = ports
        self.cores = cores
        self.reader = reader
        self.config = settings
        self.management = management
        self.json_revisions = json_revisions
        self.profiles = profiles
        self.credentials = ConfigurationCredentials()

    @handle_conflicts(message_code="inbound_port_conflict")
    @transactional
    async def create(self, data: ConfigurationCreate) -> ConfigurationModel:
        if isinstance(data.options, OpenVpnOptions):
            OpenVpnConfigurationPolicy.validate(
                data.options, self.config.openvpn
            )
        node = await self.nodes.get(data.node_id)
        port = (
            data.listen_port
            if data.listen_port is not None
            else node.public_port
        )
        network = (
            data.options.transport
            if isinstance(data.options, OpenVpnOptions)
            else "dual"
            if data.options.protocol == "shadowsocks"
            else "udp"
            if data.options.protocol in {"wireguard", "hysteria2"}
            else "tcp"
        )
        core = (
            await self.cores.get(data.core_id)
            if data.core_id is not None
            else await self.cores.default(node.id, data.options.protocol)
        )
        compatible = data.options.protocol in self.cores.supported_protocols(
            core.kind
        )
        if core.node_id != node.id or not compatible:
            raise ConflictException(
                message="هسته و پروتکل این ورودی سازگار نیستند.",
                message_code="core_protocol_mismatch",
                unique_dict={"core_id": core.id},
            )
        stored = await asyncio.to_thread(
            self.credentials.settings, data.options
        )
        result = await self.repo.create(
            ConfigurationModel(
                node_id=node.id,
                core_id=core.id,
                listen_port=port,
                port_network=network,
                label=data.label,
                protocol=data.options.protocol,
                encrypted_settings=(
                    await asyncio.to_thread(
                        ServerJsonComposition.encode,
                        stored,
                        self.config.configuration_encryption_key,
                    )
                ),
            )
        )
        if isinstance(data.options, OpenVpnOptions):
            await self.management.reserve(
                OpenVpnSocketModel(
                    configuration_id=result.id,
                    node_id=node.id,
                    path=data.options.management_socket,
                )
            )
        if network in {"tcp", "dual"}:
            await self.ports.create(
                InboundPortModel(
                    configuration_id=result.id,
                    node_id=node.id,
                    port=port,
                    network="tcp",
                )
            )
        if network in {"udp", "dual"}:
            await self.ports.create(
                InboundPortModel(
                    configuration_id=result.id,
                    node_id=node.id,
                    port=port,
                    network="udp",
                )
            )
        return result

    @transactional
    async def update(
        self, id: int, data: ConfigurationUpdate
    ) -> ConfigurationModel:
        existing = await self.repo.locked(id)
        if existing is None:
            raise NotFoundException(
                message="کانفیگ پیدا نشد.",
                message_code="configuration_not_found",
                entity="configuration",
                identifier="id",
                identifier_value=id,
            )
        if (
            data.expected_revision is not None
            and existing.revision != data.expected_revision
        ):
            raise ConflictException(
                message="ورودی تغییر کرده است؛ نسخهٔ تازه را دریافت کنید.",
                message_code="configuration_revision_conflict",
                unique_dict={"configuration_id": id},
            )
        stored = await self.settings(id)
        if isinstance(data.options, OpenVpnOptions):
            OpenVpnConfigurationPolicy.validate(
                data.options, self.config.openvpn
            )
            old = stored.options
            if not isinstance(old, OpenVpnOptions) or (
                data.options.transport != old.transport
                or data.options.server_name != old.server_name
                or data.options.ca_name != old.ca_name
                or data.options.key_type != old.key_type
                or data.options.ca_validity_days != old.ca_validity_days
                or data.options.server_validity_days
                != old.server_validity_days
                or data.options.client_validity_days
                != old.client_validity_days
                or data.options.tls_crypt != old.tls_crypt
            ):
                raise ConflictException(
                    message="هویت گواهی و انتقال به ورودی تازه نیاز دارد.",
                    message_code="openvpn_identity_changed",
                    unique_dict={"configuration_id": id},
                )
        if data.options.protocol != existing.protocol:
            raise ConflictException(
                message="پروتکل نود قابل تغییر نیست.",
                message_code="configuration_protocol_mismatch",
                unique_dict={"configuration_id": id},
            )
        if isinstance(data.options, WireguardOptions):
            limit = self.config.operations.configuration_export_max_profiles
            profiles = await self.reader.profiles(id, limit + 1)
            if len(profiles) > limit:
                raise ConflictException(
                    message="ظرفیت بررسی پروفایل‌ها کافی نیست.",
                    message_code="configuration_export_capacity",
                    unique_dict={"configuration_id": id},
                )
            pool = ip_network(data.options.client_subnet)
            server_ip = ip_interface(data.options.server_address).ip
            invalid = any(
                row.profile.client_address is None
                or ip_interface(row.profile.client_address).ip not in pool
                or ip_interface(row.profile.client_address).ip
                in {server_ip, pool.network_address, pool.broadcast_address}
                for row in profiles
            )
            if invalid:
                raise ConflictException(
                    message="محدودهٔ جدید با کاربران ثبت‌شده سازگار نیست.",
                    message_code="wireguard_address_invalid",
                    unique_dict={"configuration_id": id},
                )
        if isinstance(data.options, OpenVpnOptions):
            await self.management.change(id, data.options.management_socket)
        updated = StoredSettings(
            options=data.options,
            server_json=stored.server_json,
            openvpn=stored.openvpn,
            private_key=stored.private_key,
            public_key=stored.public_key,
            short_id=stored.short_id,
            server_password=stored.server_password,
        )
        result = await self.repo.update_existing(
            existing,
            ConfigurationModel.patch(
                revision=existing.revision + 1,
                label=data.label,
                encrypted_settings=(
                    await asyncio.to_thread(
                        ServerJsonComposition.encode,
                        updated,
                        self.config.configuration_encryption_key,
                    )
                ),
            ),
        )
        return result

    async def get(self, id: int) -> ConfigurationModel:
        result = await self.repo.get_by_id(id)
        if result is None:
            raise NotFoundException(
                message="کانفیگ پیدا نشد.",
                message_code="configuration_not_found",
                entity="configuration",
                identifier="id",
                identifier_value=id,
            )
        return result

    async def settings(self, id: int) -> StoredSettings:
        configuration = await self.get(id)
        result = await asyncio.to_thread(
            ServerJsonComposition.decode,
            configuration.encrypted_settings,
            self.config.configuration_encryption_key,
        )
        return result

    async def search(
        self, data: ConfigurationSearch
    ) -> ServicePage[ConfigurationModel]:
        limit = page_size(self.config, data.per_page)
        result = await self.repo.page(
            data.node_id, data.core_id, (data.page - 1) * limit, limit
        )
        return service_page(result, limit)

    async def server_json(self, id: int) -> ServerJsonState:
        configuration = await self.get(id)
        core = await self.cores.get(configuration.core_id)
        stored = await self.settings(id)
        return ServerJsonState(
            configuration_id=id,
            revision=configuration.revision,
            core_kind=core.kind,
            supported=core.kind in ServerJsonComposition.kinds,
            capacity=self.config.configuration_json,
            document=stored.server_json,
        )

    async def validate_document(
        self, id: int, document: ServerJsonDocument | None
    ) -> ServerJsonDocument | None:
        if document is None:
            return None
        configuration = await self.get(id)
        core = await self.cores.get(configuration.core_id)
        capacity = self.config.configuration_json
        if (
            core.kind not in ServerJsonComposition.kinds
            or capacity is None
            or not capacity.enabled
        ):
            raise ConflictException(
                message="ویرایش JSON هسته برای این ورودی فعال نیست.",
                message_code="configuration_json_disabled",
                unique_dict={"configuration_id": id},
            )
        if document.mode == "experimental":
            assigned = await self.profiles.existing_ids(id, 1)
            if assigned:
                raise ConflictException(
                    message="ورودی دارای کاربر را نمی‌توان آزمایشی کرد.",
                    message_code="configuration_json_assigned",
                    unique_dict={"configuration_id": id},
                )
        try:
            normalized = await asyncio.to_thread(
                ServerJsonComposition.normalize, document, capacity
            )
        except (ValueError, RecursionError) as error:
            raise ConflictException(
                message=(
                    "JSON معتبر نیست؛ ساختار، نشانگر ورودی "
                    "و ظرفیت مجاز را بررسی کنید."
                ),
                message_code="configuration_json_invalid",
                unique_dict={"configuration_id": id},
            ) from error
        return normalized

    @transactional
    async def update_server_json(
        self, id: int, staff_id: int, data: ServerJsonUpdate
    ) -> ConfigurationModel:
        existing = await self.repo.locked(id)
        if existing is None:
            raise NotFoundException(
                message="کانفیگ پیدا نشد.",
                message_code="configuration_not_found",
                entity="configuration",
                identifier="id",
                identifier_value=id,
            )
        if existing.revision != data.expected_revision:
            raise ConflictException(
                message="ورودی تغییر کرده است؛ نسخهٔ تازه را دریافت کنید.",
                message_code="configuration_revision_conflict",
                unique_dict={"configuration_id": id},
            )
        normalized = await self.validate_document(id, data.document)
        stored = await self.settings(id)
        stored.server_json = normalized
        encrypted = await asyncio.to_thread(
            ServerJsonComposition.encode,
            stored,
            self.config.configuration_encryption_key,
        )
        await self.json_revisions.create(
            ConfigurationJsonRevisionModel(
                configuration_id=id,
                revision=existing.revision,
                staff_id=staff_id,
                reason=data.reason,
                encrypted_settings=existing.encrypted_settings,
            )
        )
        result = await self.repo.update_existing(
            existing,
            ConfigurationModel.patch(
                revision=existing.revision + 1, encrypted_settings=encrypted
            ),
        )
        return result

    async def json_history(
        self, id: int, data: ServerJsonHistorySearch
    ) -> ServicePage[ServerJsonRevision]:
        await self.get(id)
        limit = page_size(self.config, data.per_page)
        result = await self.json_revisions.page(
            id, (data.page - 1) * limit, limit
        )
        decoded = await asyncio.to_thread(
            ServerJsonComposition.history,
            result.items,
            self.config.configuration_encryption_key,
        )
        page = service_page(result, limit)
        return ServicePage(
            items=decoded, per_page=page.per_page, total_items=page.total_items
        )

    @transactional
    async def restore_server_json(
        self, id: int, revision_id: int, staff_id: int, data: ServerJsonRestore
    ) -> ConfigurationModel:
        existing = await self.repo.locked(id)
        if existing is None:
            raise NotFoundException(
                message="کانفیگ پیدا نشد.",
                message_code="configuration_not_found",
                entity="configuration",
                identifier="id",
                identifier_value=id,
            )
        if existing.revision != data.expected_revision:
            raise ConflictException(
                message="ورودی تغییر کرده است؛ نسخهٔ تازه را دریافت کنید.",
                message_code="configuration_revision_conflict",
                unique_dict={"configuration_id": id},
            )
        revision = await self.json_revisions.get_by_id(revision_id)
        if revision is None or revision.configuration_id != id:
            raise NotFoundException(
                message="نسخهٔ ذخیره‌شده پیدا نشد.",
                message_code="configuration_json_revision_not_found",
                entity="configuration_json_revision",
                identifier="id",
                identifier_value=revision_id,
            )
        old = await asyncio.to_thread(
            ServerJsonComposition.decode,
            revision.encrypted_settings,
            self.config.configuration_encryption_key,
        )
        normalized = await self.validate_document(id, old.server_json)
        stored = await self.settings(id)
        stored.server_json = normalized
        encrypted = await asyncio.to_thread(
            ServerJsonComposition.encode,
            stored,
            self.config.configuration_encryption_key,
        )
        await self.json_revisions.create(
            ConfigurationJsonRevisionModel(
                configuration_id=id,
                revision=existing.revision,
                staff_id=staff_id,
                reason=data.reason,
                encrypted_settings=existing.encrypted_settings,
            )
        )
        result = await self.repo.update_existing(
            existing,
            ConfigurationModel.patch(
                revision=existing.revision + 1, encrypted_settings=encrypted
            ),
        )
        return result

    async def server(self, id: int) -> ConfigurationDownload:
        configuration = await self.get(id)
        core = await self.cores.get(configuration.core_id)
        if configuration.protocol not in self.cores.supported_protocols(
            core.kind
        ):
            raise ConflictException(
                message="هسته و پروتکل این ورودی سازگار نیستند.",
                message_code="core_protocol_mismatch",
                unique_dict={"core_id": core.id},
            )
        node = await self.nodes.get(configuration.node_id)
        settings = await self.settings(id)
        if (
            settings.server_json is not None
            and settings.server_json.mode == "experimental"
        ):
            return ConfigurationDownload(
                f"configuration-{id}.json",
                settings.server_json.source,
                "application/json",
            )
        limit = self.config.operations.configuration_export_max_profiles
        facts = await self.reader.profiles(id, limit + 1)
        if len(facts) > limit:
            raise ConflictException(
                message="تعداد پروفایل‌ها از ظرفیت خروجی بیشتر است.",
                message_code="configuration_export_capacity",
                unique_dict={"configuration_id": id},
            )
        result = await asyncio.to_thread(
            ServerConfigurationRenderer(
                self.config.configuration_encryption_key
            ).render,
            ConnectionEndpoint(
                configuration.id, node.public_host, configuration.listen_port
            ),
            core.kind,
            settings,
            [ServerExportInputs.profile(row) for row in facts],
        )
        return result

    async def server_many(
        self, configuration_ids: list[int]
    ) -> list[ConfigurationServerExport]:
        capacity = self.config.core_exports
        if capacity is None or not capacity.enabled:
            raise ConflictException(
                message="Core exports are disabled.",
                message_code="core_export_disabled",
                unique_dict={},
            )
        if not configuration_ids or len(configuration_ids) != len(
            set(configuration_ids)
        ):
            raise ConflictException(
                message="Unique configuration IDs are required.",
                message_code="core_export_selection",
                unique_dict={},
            )
        if len(configuration_ids) > capacity.max_configurations:
            raise ConflictException(
                message="Configuration export capacity exceeded.",
                message_code="core_export_capacity",
                unique_dict={},
            )
        facts = await self.reader.server_configurations(configuration_ids)
        found = {row.configuration.id for row in facts}
        if found != set(configuration_ids):
            raise NotFoundException(
                message="Configuration not found.",
                message_code="configuration_not_found",
                entity="configuration",
                identifier="id",
                identifier_value=next(
                    id for id in configuration_ids if id not in found
                ),
            )
        profiles = await self.reader.profiles_many(
            configuration_ids, capacity.max_profiles + 1
        )
        if len(profiles) > capacity.max_profiles:
            raise ConflictException(
                message="Profile export capacity exceeded.",
                message_code="core_export_capacity",
                unique_dict={},
            )
        result = await asyncio.to_thread(
            ConfigurationServerBatchRenderer(self.config).render,
            [ServerExportInputs.configuration(row) for row in facts],
            [ServerExportInputs.profile(row) for row in profiles],
        )
        return result

    def openvpn_policy(self) -> OpenVpnCapacity | None:
        return self.config.openvpn
