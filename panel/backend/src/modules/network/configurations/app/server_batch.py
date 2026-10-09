from papilio.errors.exceptions import ConflictException
from papilio.security.crypto import decrypt

from src.config.settings import PapilioSettings
from src.modules.network.configurations.app.server_exports import (
    ServerConfigurationRenderer,
)
from src.modules.network.configurations.domain.results import (
    ConfigurationServerExport,
    ServerConfigurationInput,
    ServerProfileInput,
    StoredSettings,
)
from src.modules.network.cores.app.protocols import CoreProtocols


class ConfigurationServerBatchRenderer:
    def __init__(self, settings: PapilioSettings) -> None:
        self.settings = settings

    def render(
        self,
        configurations: list[ServerConfigurationInput],
        profiles: list[ServerProfileInput],
    ) -> list[ConfigurationServerExport]:
        grouped: dict[int, list[ServerProfileInput]] = {}
        for profile in profiles:
            grouped.setdefault(profile.configuration_id, []).append(profile)
        renderer = ServerConfigurationRenderer(
            self.settings.configuration_encryption_key
        )
        result: list[ConfigurationServerExport] = []
        output_bytes = 0
        capacity = self.settings.core_exports
        assert capacity is not None
        for facts in configurations:
            configuration = facts.endpoint
            if facts.protocol not in CoreProtocols.supported(facts.core_kind):
                raise ConflictException(
                    message="Core and protocol do not match.",
                    message_code="core_protocol_mismatch",
                    unique_dict={"configuration_id": configuration.id},
                )
            clients = grouped.get(configuration.id, [])
            if (
                len(clients)
                > self.settings.operations.configuration_export_max_profiles
            ):
                raise ConflictException(
                    message="Configuration profile capacity exceeded.",
                    message_code="configuration_export_capacity",
                    unique_dict={"configuration_id": configuration.id},
                )
            settings = StoredSettings.model_validate_json(
                decrypt(
                    facts.encrypted_settings,
                    self.settings.configuration_encryption_key,
                )
            )
            download = renderer.render(
                configuration, facts.core_kind, settings, clients
            )
            output_bytes += len(download.content.encode())
            if output_bytes > capacity.max_output_bytes:
                raise ConflictException(
                    message="Core export byte capacity exceeded.",
                    message_code="core_export_output_capacity",
                    unique_dict={},
                )
            result.append(
                ConfigurationServerExport(
                    configuration.id, facts.revision, download
                )
            )
        return result
