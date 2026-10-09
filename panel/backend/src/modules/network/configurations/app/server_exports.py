from datetime import UTC, datetime

from papilio.errors.exceptions import ConflictException
from papilio.security.crypto import decrypt

from src.modules.network.configurations.app.availability import (
    ServerProfileAvailability,
)
from src.modules.network.configurations.app.counter_identity import (
    profile_counter_identity,
)
from src.modules.network.configurations.app.exports import ProtocolExporter
from src.modules.network.configurations.app.server_json import (
    ServerJsonComposition,
)
from src.modules.network.configurations.app.sing_box import SingBoxExporter
from src.modules.network.configurations.domain.dtos import ShadowsocksOptions
from src.modules.network.configurations.domain.openvpn import OpenVpnOptions
from src.modules.network.configurations.domain.results import (
    ClientCredentials,
    ConfigurationDownload,
    ConnectionEndpoint,
    ServerProfileInput,
    StoredSettings,
)


class ServerConfigurationRenderer:
    def __init__(self, key: str) -> None:
        self.key = key
        self.exporter = ProtocolExporter()
        self.sing_box = SingBoxExporter()

    def render(
        self,
        endpoint: ConnectionEndpoint,
        core_kind: str,
        settings: StoredSettings,
        facts: list[ServerProfileInput],
    ) -> ConfigurationDownload:
        id = endpoint.id
        if (
            settings.server_json is not None
            and settings.server_json.mode == "experimental"
        ):
            return ConfigurationDownload(
                f"configuration-{id}.json",
                settings.server_json.source,
                "application/json",
            )
        now = datetime.now(UTC).replace(tzinfo=None)
        eligible = [
            row
            for row in facts
            if ServerProfileAvailability.eligible(
                services_available=row.services_available,
                status=row.status,
                request_state=row.request_state,
                expires_at=row.expires_at,
                quota_bytes=row.quota_bytes,
                used_bytes=row.used_bytes,
                now=now,
            )
        ]
        eligible_ids = {row.profile_id for row in eligible}
        credential_facts = (
            facts if isinstance(settings.options, OpenVpnOptions) else eligible
        )
        credentials = [
            ClientCredentials.model_validate_json(
                decrypt(row.encrypted_credentials, self.key)
            )
            for row in credential_facts
        ]
        clients = [
            (value, row.client_address)
            for row, value in zip(credential_facts, credentials, strict=True)
            if row.profile_id in eligible_ids
        ]
        if isinstance(settings.options, ShadowsocksOptions) and not clients:
            raise ConflictException(
                message="برای خروجی شادوساکس، یک کاربر معتبر لازم است.",
                message_code="configuration_no_clients",
                unique_dict={"configuration_id": id},
            )
        revoked = [
            value
            for row, value in zip(credential_facts, credentials, strict=True)
            if row.profile_id not in eligible_ids
        ]
        if isinstance(settings.options, OpenVpnOptions):
            try:
                result = self.exporter.server(
                    endpoint,
                    settings,
                    clients,
                    revoked,
                )
            except ValueError as error:
                raise ConflictException(
                    message="گواهی OpenVPN معتبر نیست؛ ورودی را بازبینی کنید.",
                    message_code="openvpn_certificate_unavailable",
                    unique_dict={"configuration_id": id},
                ) from error
            return result
        if core_kind == "sing_box":
            result = self.sing_box.server(endpoint, settings, clients)
        else:
            result = self.exporter.server(
                endpoint,
                settings,
                clients,
                counter_identities=[
                    profile_counter_identity(row.profile_id, row.generation)
                    for row in eligible
                ],
            )
        if settings.server_json is not None:
            result = ServerJsonComposition.apply(result, settings.server_json)
        return result
