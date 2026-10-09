import json

from src.modules.network.configurations.domain.dtos import (
    HysteriaOptions,
    RealityOptions,
    ShadowsocksOptions,
    TlsOptions,
)
from src.modules.network.configurations.domain.results import (
    ClientCredentials,
    ConfigurationDownload,
    ConnectionEndpoint,
    StoredSettings,
)


class SingBoxExporter:
    def server(
        self,
        node: ConnectionEndpoint,
        settings: StoredSettings,
        clients: list[tuple[ClientCredentials, str | None]],
    ) -> ConfigurationDownload:
        options = settings.options
        if not isinstance(
            options,
            (RealityOptions, TlsOptions, ShadowsocksOptions, HysteriaOptions),
        ):
            raise ValueError("Unsupported Sing-box inbound")
        inbound: dict[str, object] = {
            "tag": f"inbound-{node.id}",
            "listen": options.listen_address,
            "listen_port": node.public_port,
        }
        if isinstance(options, RealityOptions):
            inbound.update(
                type="vless",
                users=[
                    {
                        "name": client.identity,
                        "uuid": client.identity,
                        "flow": "xtls-rprx-vision",
                    }
                    for client, _ in clients
                ],
                tls={
                    "enabled": True,
                    "server_name": options.server_name,
                    "reality": {
                        "enabled": True,
                        "handshake": {
                            "server": options.server_name,
                            "server_port": options.target_port,
                        },
                        "private_key": settings.private_key,
                        "short_id": [settings.short_id],
                    },
                },
            )
        elif isinstance(options, ShadowsocksOptions):
            inbound.update(
                type="shadowsocks",
                method="2022-blake3-aes-256-gcm",
                password=settings.server_password,
                users=[
                    {"name": client.identity, "password": client.password}
                    for client, _ in clients
                ],
            )
        else:
            inbound["tls"] = {
                "enabled": True,
                "server_name": options.server_name,
                "certificate_path": options.certificate_path,
                "key_path": options.private_key_path,
            }
            if isinstance(options, HysteriaOptions):
                inbound.update(
                    type="hysteria2",
                    users=[
                        {
                            "name": client.identity,
                            "password": f"{client.identity}:{client.password}",
                        }
                        for client, _ in clients
                    ],
                )
            else:
                protocol = {
                    "vless_tls": "vless",
                    "vmess_tls": "vmess",
                    "trojan_tls": "trojan",
                }[options.protocol]
                inbound["type"] = protocol
                inbound["users"] = [
                    {
                        "name": client.identity,
                        ("password" if protocol == "trojan" else "uuid"): (
                            client.password
                            if protocol == "trojan"
                            else client.identity
                        ),
                    }
                    for client, _ in clients
                ]
                if options.transport == "ws":
                    inbound["transport"] = {
                        "type": "ws",
                        "path": options.transport_path,
                    }
                elif options.transport == "grpc":
                    inbound["transport"] = {
                        "type": "grpc",
                        "service_name": options.transport_path,
                    }
        content = {
            "inbounds": [inbound],
            "outbounds": [{"type": "direct", "tag": "direct"}],
            "route": {"final": "direct"},
        }
        return ConfigurationDownload(
            filename=f"inbound-{node.id}-sing-box.json",
            content=json.dumps(content, indent=2),
            media_type="application/json",
        )
