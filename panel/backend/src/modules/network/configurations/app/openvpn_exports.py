from ipaddress import ip_network

from src.modules.network.configurations.domain.openvpn import (
    OpenVpnClientCertificate,
    OpenVpnOptions,
    OpenVpnPkiMaterial,
    OpenVpnTun,
)
from src.modules.network.configurations.domain.results import (
    ConnectionEndpoint,
)


class OpenVpnExporter:
    @staticmethod
    def inline(tag: str, content: str) -> str:
        return f"<{tag}>\n{content.rstrip()}\n</{tag}>"

    def server(
        self,
        endpoint: ConnectionEndpoint,
        options: OpenVpnOptions,
        material: OpenVpnPkiMaterial,
        crl: str,
    ) -> str:
        lines = [
            f"local {options.listen_address}",
            f"port {endpoint.public_port}",
            "proto udp" if options.transport == "udp" else "proto tcp-server",
            f"dev {options.topology.mode}",
            "dh none",
            "verify-client-cert require",
            "remote-cert-tls client",
            "allow-compression no",
            "disable-dco",
            f"data-ciphers {':'.join(options.data_ciphers)}",
            f"tls-version-min {options.tls_min_version}",
            f"keepalive {options.keepalive_seconds} {options.restart_seconds}",
            f"max-clients {options.max_clients}",
            f"verb {options.verbosity}",
            f"management {options.management_socket} unix",
            "management-client",
            "management-client-auth",
            "management-hold",
            "auth-user-pass-optional",
        ]
        pool = ip_network(options.topology.network)
        if isinstance(options.topology, OpenVpnTun):
            lines.extend(
                [
                    "topology subnet",
                    f"server {pool.network_address} {pool.netmask}",
                ]
            )
        else:
            bridge = options.topology
            lines.append(
                f"server-bridge {bridge.bridge_address} {pool.netmask} "
                f"{bridge.pool_start} {bridge.pool_end}"
            )
        if options.redirect_gateway:
            lines.append('push "redirect-gateway def1"')
        if options.client_to_client:
            lines.append("client-to-client")
        for network in options.routes:
            route = ip_network(network)
            lines.append(
                f'push "route {route.network_address} {route.netmask}"'
                if route.version == 4
                else f'push "route-ipv6 {route}"'
            )
        lines.extend(
            f'push "dhcp-option DNS {address}"' for address in options.dns
        )
        lines.extend(
            [
                self.inline("ca", material.ca_certificate),
                self.inline("cert", material.server_certificate),
                self.inline("key", material.server_private_key),
                self.inline("crl-verify", crl),
            ]
        )
        if material.tls_crypt_key is not None:
            lines.append(self.inline("tls-crypt", material.tls_crypt_key))
        return "\n".join(lines) + "\n"

    def client(
        self,
        endpoint: ConnectionEndpoint,
        options: OpenVpnOptions,
        material: OpenVpnPkiMaterial,
        credentials: OpenVpnClientCertificate,
    ) -> str:
        if credentials.private_key is None:
            raise ValueError("The private client key is unavailable")
        lines = [
            "client",
            f"dev {options.topology.mode}",
            "proto udp" if options.transport == "udp" else "proto tcp-client",
            f"remote {endpoint.public_host} {endpoint.public_port}",
            "nobind",
            "persist-key",
            "persist-tun",
            "remote-cert-tls server",
            f"verify-x509-name {options.server_name} name",
            "allow-compression no",
            f"data-ciphers {':'.join(options.data_ciphers)}",
            f"tls-version-min {options.tls_min_version}",
            f"verb {options.verbosity}",
            self.inline("ca", material.ca_certificate),
            self.inline("cert", credentials.certificate),
            self.inline("key", credentials.private_key),
        ]
        if material.tls_crypt_key is not None:
            lines.append(self.inline("tls-crypt", material.tls_crypt_key))
        return "\n".join(lines) + "\n"
