import base64
import json
import secrets
from datetime import UTC, datetime
from urllib.parse import quote, urlencode
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from papilio.errors.exceptions import ConflictException

from src.modules.network.configurations.app.openvpn_exports import (
    OpenVpnExporter,
)
from src.modules.network.configurations.app.openvpn_pki import (
    OpenVpnCertificateAuthority,
)
from src.modules.network.configurations.domain.dtos import (
    ConfigurationOptions,
    HysteriaOptions,
    RealityOptions,
    ShadowsocksOptions,
    TlsOptions,
    WireguardOptions,
)
from src.modules.network.configurations.domain.openvpn import OpenVpnOptions
from src.modules.network.configurations.domain.results import (
    ClientCredentials,
    ConfigurationDownload,
    ConnectionEndpoint,
    StoredSettings,
)


def endpoint(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


class ConfigurationCredentials:
    @staticmethod
    def keypair(urlsafe: bool) -> tuple[str, str]:
        private = X25519PrivateKey.generate()
        encode = base64.urlsafe_b64encode if urlsafe else base64.b64encode
        secret = encode(
            private.private_bytes(
                Encoding.Raw, PrivateFormat.Raw, NoEncryption()
            )
        ).decode()
        public = encode(
            private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        ).decode()
        return (
            (secret.rstrip("="), public.rstrip("="))
            if urlsafe
            else (secret, public)
        )

    def settings(self, options: ConfigurationOptions) -> StoredSettings:
        result = StoredSettings(options=options)
        if isinstance(options, OpenVpnOptions):
            result.openvpn = OpenVpnCertificateAuthority().create(options)
        if isinstance(options, (RealityOptions, WireguardOptions)):
            result.private_key, result.public_key = self.keypair(
                isinstance(options, RealityOptions)
            )
        if isinstance(options, RealityOptions):
            result.short_id = secrets.token_hex(8)
        if isinstance(options, ShadowsocksOptions):
            result.server_password = base64.b64encode(
                secrets.token_bytes(32)
            ).decode()
        return result

    def client(
        self,
        options: ConfigurationOptions,
        settings: StoredSettings | None = None,
    ) -> ClientCredentials:
        result = ClientCredentials(identity=str(uuid4()))
        if isinstance(options, OpenVpnOptions):
            try:
                if settings is None or settings.openvpn is None:
                    raise ValueError(
                        "OpenVPN certificate authority is missing"
                    )
                result.openvpn = OpenVpnCertificateAuthority().issue(
                    options, settings.openvpn, result.identity
                )
            except (ValueError, InvalidSignature) as error:
                raise ConflictException(
                    message="گواهی OpenVPN معتبر نیست؛ ورودی را بازبینی کنید.",
                    message_code="openvpn_certificate_unavailable",
                    unique_dict={},
                ) from error
        if isinstance(options, WireguardOptions):
            result.private_key, result.public_key = self.keypair(False)
            result.preshared_key = base64.b64encode(
                secrets.token_bytes(32)
            ).decode()
        elif isinstance(options, ShadowsocksOptions):
            result.password = base64.b64encode(
                secrets.token_bytes(32)
            ).decode()
        elif isinstance(options, HysteriaOptions) or (
            isinstance(options, TlsOptions)
            and options.protocol == "trojan_tls"
        ):
            result.password = secrets.token_urlsafe(32)
        return result


class ProtocolExporter:
    def server(
        self,
        node: ConnectionEndpoint,
        settings: StoredSettings,
        clients: list[tuple[ClientCredentials, str | None]],
        revoked: list[ClientCredentials] | None = None,
        counter_identities: list[str] | None = None,
    ) -> ConfigurationDownload:
        options = settings.options
        if isinstance(options, OpenVpnOptions):
            if settings.openvpn is None or revoked is None:
                raise ValueError(
                    "OpenVPN requires authority material "
                    "and explicit revocation facts"
                )
            if not OpenVpnCertificateAuthority.server_valid(
                settings.openvpn, options.server_name, datetime.now(UTC)
            ):
                raise ValueError("OpenVPN server certificate is unavailable")
            certificates = [
                value.openvpn for value in revoked if value.openvpn is not None
            ]
            crl = OpenVpnCertificateAuthority().revocations(
                settings.openvpn, certificates, options.crl_validity_seconds
            )
            content = OpenVpnExporter().server(
                node, options, settings.openvpn, crl
            )
            return ConfigurationDownload(
                f"node-{node.id}-openvpn.conf", content, "text/plain"
            )
        if isinstance(options, WireguardOptions):
            lines = [
                "[Interface]",
                f"PrivateKey = {settings.private_key}",
                f"Address = {options.server_address}",
                f"ListenPort = {node.public_port}",
            ]
            for client, address in clients:
                lines.extend(
                    [
                        "",
                        "[Peer]",
                        f"PublicKey = {client.public_key}",
                        f"PresharedKey = {client.preshared_key}",
                        f"AllowedIPs = {address}",
                    ]
                )
            return ConfigurationDownload(
                f"node-{node.id}-wireguard.conf",
                "\n".join(lines) + "\n",
                "text/plain",
            )
        if isinstance(options, HysteriaOptions):
            content = {
                "listen": endpoint(options.listen_address, node.public_port),
                "tls": {
                    "cert": options.certificate_path,
                    "key": options.private_key_path,
                },
                "auth": {
                    "type": "userpass",
                    "userpass": {
                        client.identity: client.password
                        for client, _ in clients
                    },
                },
            }
            return ConfigurationDownload(
                f"node-{node.id}-hysteria2.json",
                json.dumps(content, indent=2),
                "application/json",
            )
        stream: dict[str, object] = {"network": "tcp"}
        protocol = "vless"
        counter_clients = list(
            zip(
                clients,
                counter_identities or [value.identity for value, _ in clients],
                strict=True,
            )
        )
        users: list[dict[str, object]] = []
        inbound_settings: dict[str, object]
        if isinstance(options, RealityOptions):
            stream.update(
                security="reality",
                realitySettings={
                    "dest": endpoint(options.server_name, options.target_port),
                    "serverNames": [options.server_name],
                    "privateKey": settings.private_key,
                    "shortIds": [settings.short_id],
                },
            )
            users = [
                {
                    "id": c.identity,
                    "email": counter,
                    "level": 0,
                    "flow": "xtls-rprx-vision",
                }
                for (c, _), counter in counter_clients
            ]
            inbound_settings = {"clients": users, "decryption": "none"}
        elif isinstance(options, TlsOptions):
            protocol = {
                "vless_tls": "vless",
                "vmess_tls": "vmess",
                "trojan_tls": "trojan",
            }[options.protocol]
            stream.update(
                network=options.transport,
                security="tls",
                tlsSettings={
                    "certificates": [
                        {
                            "certificateFile": options.certificate_path,
                            "keyFile": options.private_key_path,
                        }
                    ]
                },
            )
            if options.transport == "ws":
                stream["wsSettings"] = {"path": options.transport_path}
            elif options.transport == "grpc":
                stream["grpcSettings"] = {
                    "serviceName": options.transport_path
                }
            users = [
                {
                    ("password" if protocol == "trojan" else "id"): (
                        c.password if protocol == "trojan" else c.identity
                    ),
                    "email": counter,
                    "level": 0,
                }
                for (c, _), counter in counter_clients
            ]
            inbound_settings = {"clients": users}
            if protocol == "vless":
                inbound_settings["decryption"] = "none"
        else:
            protocol = "shadowsocks"
            inbound_settings = {
                "method": "2022-blake3-aes-256-gcm",
                "password": settings.server_password,
                "clients": [
                    {"password": c.password, "email": counter, "level": 0}
                    for (c, _), counter in counter_clients
                ],
                "network": "tcp,udp",
            }
        content = {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {
                    "tag": f"node-{node.id}",
                    "listen": options.listen_address,
                    "port": node.public_port,
                    "protocol": protocol,
                    "settings": inbound_settings,
                    "streamSettings": stream,
                }
            ],
            "outbounds": [{"protocol": "freedom", "tag": "direct"}],
        }
        return ConfigurationDownload(
            f"node-{node.id}-xray-v26.3.27.json",
            json.dumps(content, indent=2),
            "application/json",
        )

    def client(
        self,
        node: ConnectionEndpoint,
        settings: StoredSettings,
        credentials: ClientCredentials,
        address: str | None,
        label: str,
    ) -> str:
        options = settings.options
        if isinstance(options, OpenVpnOptions):
            if settings.openvpn is None or credentials.openvpn is None:
                raise ValueError("OpenVPN certificate material is missing")
            if not OpenVpnCertificateAuthority.server_valid(
                settings.openvpn, options.server_name, datetime.now(UTC)
            ):
                raise ValueError("OpenVPN server certificate is unavailable")
            if not OpenVpnCertificateAuthority.client_valid(
                settings.openvpn,
                credentials.openvpn,
                credentials.identity,
                datetime.now(UTC),
            ):
                raise ValueError("OpenVPN client certificate is unavailable")
            return OpenVpnExporter().client(
                node, options, settings.openvpn, credentials.openvpn
            )
        remote = endpoint(node.public_host, node.public_port)
        fragment = quote(label, safe="")
        if isinstance(options, WireguardOptions):
            return "\n".join(
                [
                    "[Interface]",
                    f"PrivateKey = {credentials.private_key}",
                    f"Address = {address}",
                    f"DNS = {', '.join(options.dns)}",
                    "",
                    "[Peer]",
                    f"PublicKey = {settings.public_key}",
                    f"PresharedKey = {credentials.preshared_key}",
                    f"Endpoint = {remote}",
                    f"AllowedIPs = {', '.join(options.allowed_ips)}",
                    "",
                ]
            )
        if isinstance(options, HysteriaOptions):
            auth = quote(
                f"{credentials.identity}:{credentials.password}", safe=""
            )
            parameters = urlencode({"sni": options.server_name})
            return f"hysteria2://{auth}@{remote}?{parameters}#{fragment}"
        if isinstance(options, ShadowsocksOptions):
            auth = (
                base64.urlsafe_b64encode(
                    f"2022-blake3-aes-256-gcm:{settings.server_password}:{credentials.password}".encode()
                )
                .decode()
                .rstrip("=")
            )
            return f"ss://{auth}@{remote}#{fragment}"
        params: dict[str, str | None] = {
            "type": "tcp",
            "security": "reality",
            "sni": options.server_name,
        }
        if isinstance(options, RealityOptions):
            params.update(
                pbk=settings.public_key,
                sid=settings.short_id,
                flow="xtls-rprx-vision",
                fp="chrome",
                encryption="none",
            )
            scheme = "vless"
        else:
            params.update(type=options.transport, security="tls")
            if options.transport == "ws":
                params.update(
                    path=options.transport_path, host=options.server_name
                )
            elif options.transport == "grpc":
                params.update(serviceName=options.transport_path)
            if options.protocol == "vmess_tls":
                record = {
                    "v": "2",
                    "ps": label,
                    "add": node.public_host,
                    "port": str(node.public_port),
                    "id": credentials.identity,
                    "aid": "0",
                    "scy": "auto",
                    "net": options.transport,
                    "type": "none",
                    "host": options.server_name,
                    "path": options.transport_path or "",
                    "tls": "tls",
                    "sni": options.server_name,
                }
                return (
                    "vmess://"
                    + base64.b64encode(json.dumps(record).encode()).decode()
                )
            scheme = "trojan" if options.protocol == "trojan_tls" else "vless"
            if scheme == "vless":
                params["encryption"] = "none"
        identity = (
            credentials.password
            if scheme == "trojan"
            else credentials.identity
        )
        parameters = urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
        user = quote(str(identity), safe="")
        return f"{scheme}://{user}@{remote}?{parameters}#{fragment}"
