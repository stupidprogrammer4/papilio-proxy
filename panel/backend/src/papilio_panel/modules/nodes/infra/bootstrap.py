"""Serialize only agent-side credentials into a private bootstrap archive."""

import io
import json
import zipfile
from dataclasses import asdict

from ..domain import IssuedCredentials, NodeRead


class NativeBootstrapArchive:
    def build(self, node: NodeRead, credentials: IssuedCredentials) -> bytes:
        configuration = asdict(node.runtime) | {
            "node_id": str(node.id),
            "deployment_id": str(node.deployment_id),
            "tls_certificate_file": "server.crt",
            "tls_key_file": "server.key",
            "client_ca_file": "client-ca.crt",
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, content in (
                ("agent.json", json.dumps(configuration, indent=2)),
                ("server.crt", credentials.server_certificate),
                ("server.key", credentials.private_keys.server),
                ("client-ca.crt", credentials.authority_certificate),
            ):
                info = zipfile.ZipInfo(filename)
                info.external_attr = 0o100600 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, content)
        return output.getvalue()
