class CoreProtocols:
    @staticmethod
    def supported(kind: str) -> tuple[str, ...]:
        common = (
            "vless_reality",
            "vless_tls",
            "vmess_tls",
            "trojan_tls",
            "shadowsocks",
        )
        if kind == "xray":
            return common
        if kind == "sing_box":
            return (*common, "hysteria2")
        if kind == "openvpn":
            return ("openvpn",)
        if kind == "wireguard":
            return ("wireguard",)
        if kind == "hysteria":
            return ("hysteria2",)
        return ()
