import base64
from datetime import datetime

from papilio.security.crypto import decrypt
from pydantic import TypeAdapter

from src.modules.accounts.customers.app.policies import CustomerAccessPolicy
from src.modules.network.configurations.app.exports import ProtocolExporter
from src.modules.network.configurations.app.openvpn_pki import (
    OpenVpnCertificateAuthority,
)
from src.modules.network.configurations.domain.dtos import (
    ConfigurationOptions,
    RealityOptions,
    WireguardOptions,
)
from src.modules.network.configurations.domain.openvpn import OpenVpnOptions
from src.modules.network.configurations.domain.results import (
    ClientCredentials,
    ConfigurationDownload,
    ConnectionEndpoint,
    StoredSettings,
    SubscriptionConfigurationFacts,
)


class ProfileDelivery:
    def __init__(self, encryption_key: str) -> None:
        self.encryption_key = encryption_key
        self.exporter = ProtocolExporter()

    def available(
        self, row: SubscriptionConfigurationFacts, now: datetime
    ) -> bool:
        group_available = row.subscription.group_id is None or (
            row.group is not None
            and row.group.is_enabled
            and row.host is not None
            and row.host.is_enabled
            and row.membership is not None
            and row.membership.is_enabled
        )
        acknowledged = not row.subscription.provisioning_managed or (
            row.profile.applied_generation == row.subscription.renewal_count
            and row.profile.applied_revision == row.configuration.revision
        )
        if (
            row.configuration.protocol in {"vless_reality", "openvpn"}
            and row.membership is not None
            and row.membership.server_name is not None
        ):
            stored = StoredSettings.model_validate_json(
                decrypt(
                    row.configuration.encrypted_settings, self.encryption_key
                )
            )
            if (
                isinstance(stored.options, (RealityOptions, OpenVpnOptions))
                and stored.options.server_name != row.membership.server_name
            ):
                return False
        if row.configuration.protocol == "openvpn":
            stored = StoredSettings.model_validate_json(
                decrypt(
                    row.configuration.encrypted_settings, self.encryption_key
                )
            )
            credentials = ClientCredentials.model_validate_json(
                decrypt(row.profile.encrypted_credentials, self.encryption_key)
            )
            if (
                not isinstance(stored.options, OpenVpnOptions)
                or stored.openvpn is None
                or credentials.openvpn is None
                or not OpenVpnCertificateAuthority.server_valid(
                    stored.openvpn, stored.options.server_name, now
                )
                or not OpenVpnCertificateAuthority.client_valid(
                    stored.openvpn,
                    credentials.openvpn,
                    credentials.identity,
                    now,
                )
            ):
                return False
        return (
            CustomerAccessPolicy.services_available(row.customer)
            and group_available
            and acknowledged
            and row.node.is_enabled
            and row.subscription.status == "active"
            and (
                row.subscription.expires_at is None
                or row.subscription.expires_at > now
            )
            and (
                row.subscription.quota_bytes is None
                or row.subscription.used_bytes < row.subscription.quota_bytes
            )
        )

    def download(
        self, row: SubscriptionConfigurationFacts
    ) -> ConfigurationDownload:
        settings = StoredSettings.model_validate_json(
            decrypt(row.configuration.encrypted_settings, self.encryption_key)
        )
        address = row.node.public_host
        port = row.configuration.listen_port
        label = row.configuration.label
        if row.host is not None and row.membership is not None:
            address = row.membership.address or row.host.address
            port = row.membership.port or row.host.port
            label = row.membership.label or row.host.label
            if row.membership.server_name is not None:
                if (
                    isinstance(
                        settings.options, (RealityOptions, OpenVpnOptions)
                    )
                    and row.membership.server_name
                    != settings.options.server_name
                ):
                    raise ValueError(
                        "REALITY host no longer matches its inbound"
                    )
                options = TypeAdapter(ConfigurationOptions).validate_python(
                    {
                        **settings.options.model_dump(),
                        "server_name": row.membership.server_name,
                    }
                )
                settings = settings.model_copy(update={"options": options})
        credentials = ClientCredentials.model_validate_json(
            decrypt(row.profile.encrypted_credentials, self.encryption_key)
        )
        content = self.exporter.client(
            ConnectionEndpoint(row.configuration.id, address, port),
            settings,
            credentials,
            row.profile.client_address,
            label,
        )
        extension = (
            "ovpn"
            if isinstance(settings.options, OpenVpnOptions)
            else "conf"
            if isinstance(settings.options, WireguardOptions)
            else "txt"
        )
        return ConfigurationDownload(
            f"profile-{row.profile.id}.{extension}", content, "text/plain"
        )

    def available_rows(
        self, rows: list[SubscriptionConfigurationFacts], now: datetime
    ) -> list[SubscriptionConfigurationFacts]:
        return [row for row in rows if self.available(row, now)]

    def has_feed(
        self, rows: list[SubscriptionConfigurationFacts], now: datetime
    ) -> bool:
        return any(
            self.available(row, now)
            and row.configuration.protocol not in {"wireguard", "openvpn"}
            for row in rows
        )

    def feed(
        self, rows: list[SubscriptionConfigurationFacts], now: datetime
    ) -> ConfigurationDownload:
        entries = []
        for row in rows:
            if not self.available(row, now) or row.configuration.protocol in {
                "wireguard",
                "openvpn",
            }:
                continue
            try:
                entries.append(self.download(row).content)
            except ValueError:
                continue
        if not entries:
            raise ValueError("No deliverable URI profiles")
        return ConfigurationDownload(
            "subscription.txt",
            base64.b64encode("\n".join(entries).encode()).decode(),
            "text/plain",
        )
