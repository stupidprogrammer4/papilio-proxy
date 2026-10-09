from dataclasses import dataclass
from datetime import datetime

from papilio.security.crypto import decrypt, encrypt

from src.modules.network.configurations.app.openvpn_pki import (
    OpenVpnCertificateAuthority,
)
from src.modules.network.configurations.domain.openvpn import (
    OpenVpnCertificate,
    OpenVpnOptions,
    OpenVpnServerMaterial,
)
from src.modules.network.configurations.domain.results import (
    ClientCredentials,
    NodeClientCredentials,
    NodeConfigurationSettings,
    StoredSettings,
)
from src.modules.network.provisioning.domain.results import ProvisionPayload


@dataclass(frozen=True, slots=True)
class ProvisionPayloadSource:
    configuration_id: int
    profile_id: int
    core_id: int
    listen_port: int
    encrypted_settings: str
    encrypted_credentials: str
    client_address: str | None


@dataclass(frozen=True, slots=True)
class RevokePayloadRefresh:
    configuration_id: int
    profile_id: int
    listen_port: int
    encrypted_settings: str
    original_encrypted_payload: str


@dataclass(frozen=True, slots=True)
class EncodedProvisionPayload:
    configuration_id: int
    profile_id: int
    ciphertext: str


class ProvisionPayloadEncoding:
    @staticmethod
    def decode(ciphertext: str, key: str) -> ProvisionPayload:
        return ProvisionPayload.model_validate_json(decrypt(ciphertext, key))

    @staticmethod
    def payload(source: ProvisionPayloadSource, key: str) -> ProvisionPayload:
        return ProvisionPayload(
            core_id=source.core_id,
            listen_port=source.listen_port,
            settings=StoredSettings.model_validate_json(
                decrypt(source.encrypted_settings, key)
            ),
            credentials=ClientCredentials.model_validate_json(
                decrypt(source.encrypted_credentials, key)
            ),
            client_address=source.client_address,
        )

    def encode(
        self, source: ProvisionPayloadSource, key: str
    ) -> EncodedProvisionPayload:
        payload = self.payload(source, key)
        return EncodedProvisionPayload(
            source.configuration_id,
            source.profile_id,
            encrypt(payload.model_dump_json(), key),
        )

    def encode_many(
        self, sources: list[ProvisionPayloadSource], key: str
    ) -> list[EncodedProvisionPayload]:
        return [
            EncodedProvisionPayload(
                source.configuration_id,
                source.profile_id,
                encrypt(self.payload(source, key).model_dump_json(), key),
            )
            for source in sources
        ]

    def refresh_revocations(
        self, sources: list[RevokePayloadRefresh], key: str
    ) -> list[EncodedProvisionPayload]:
        encoded = []
        for source in sources:
            original = self.decode(source.original_encrypted_payload, key)
            refreshed = ProvisionPayload(
                core_id=original.core_id,
                listen_port=source.listen_port,
                settings=StoredSettings.model_validate_json(
                    decrypt(source.encrypted_settings, key)
                ),
                credentials=original.credentials,
                client_address=original.client_address,
            )
            encoded.append(
                EncodedProvisionPayload(
                    source.configuration_id,
                    source.profile_id,
                    encrypt(refreshed.model_dump_json(), key),
                )
            )
        return encoded


class ProvisionNodeSecrets:
    @staticmethod
    def certificate_valid(value: ProvisionPayload, now: datetime) -> bool:
        if not isinstance(value.settings.options, OpenVpnOptions):
            return True
        material = value.settings.openvpn
        certificate = value.credentials.openvpn
        return (
            material is not None
            and certificate is not None
            and (
                OpenVpnCertificateAuthority.server_valid(
                    material, value.settings.options.server_name, now
                )
                and OpenVpnCertificateAuthority.client_valid(
                    material, certificate, value.credentials.identity, now
                )
            )
        )

    @staticmethod
    def settings(value: StoredSettings) -> NodeConfigurationSettings:
        material = value.openvpn
        return NodeConfigurationSettings(
            options=value.options,
            server_json=value.server_json,
            private_key=value.private_key,
            public_key=value.public_key,
            short_id=value.short_id,
            server_password=value.server_password,
            openvpn=None
            if material is None
            else OpenVpnServerMaterial(
                ca_certificate=material.ca_certificate,
                server_certificate=material.server_certificate,
                server_private_key=material.server_private_key,
                tls_crypt_key=material.tls_crypt_key,
            ),
        )

    @staticmethod
    def credentials(value: ClientCredentials) -> NodeClientCredentials:
        certificate = value.openvpn
        return NodeClientCredentials(
            identity=value.identity,
            password=value.password,
            private_key=value.private_key,
            public_key=value.public_key,
            preshared_key=value.preshared_key,
            openvpn=None
            if certificate is None
            else OpenVpnCertificate(
                certificate=certificate.certificate,
                serial=certificate.serial,
            ),
        )
