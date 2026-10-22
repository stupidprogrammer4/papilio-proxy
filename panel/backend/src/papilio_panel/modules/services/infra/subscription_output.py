"""Serialize the supported VLESS/TCP endpoint in a native client subscription."""

import base64
from urllib.parse import quote, urlencode

from papilio_panel.modules.cores.domain import XrayInboundRead

from ..domain import XrayCredential


class VlessSubscriptionOutput:
    def render(self, name: str, endpoint: XrayInboundRead, credential: XrayCredential) -> bytes:
        host = f"[{endpoint.public_host}]" if ":" in endpoint.public_host else endpoint.public_host
        parameters = urlencode({"encryption": "none", "type": "tcp", "security": "none"})
        label = quote(name, safe="")
        link = f"vless://{credential.identifier}@{host}:{endpoint.port}?{parameters}#{label}"
        return base64.b64encode((link + "\n").encode())
