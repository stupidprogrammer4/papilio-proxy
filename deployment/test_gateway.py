"""Gateway transport probes reject invalid origins and untrusted TLS."""

import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import check_gateway


class GatewayHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        media = "text/html" if self.path == "/" else "application/json"
        self.send_header("Content-Type", media)
        self.end_headers()
        self.wfile.write(b"fixture")

    def log_message(self, format: str, *args) -> None:
        pass


class GatewayTest(unittest.TestCase):
    def test_invalid_origin_fails_before_transport(self):
        with self.assertRaises(ValueError):
            check_gateway.check("https://user:secret@fixture.example", 1)

    def test_http_success_and_untrusted_https_refusal(self):
        import socket
        import ssl

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        server = ThreadingHTTPServer(("127.0.0.1", 0), GatewayHandler)
        self.addCleanup(server.server_close)
        original = socket.getaddrinfo
        port = server.server_address[1]

        def owned_dns(host, requested_port, *args, **kwargs):
            return original("127.0.0.1", port, *args, **kwargs)

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with patch.object(socket, "getaddrinfo", side_effect=owned_dns):
            try:
                check_gateway.check("http://fixture.example", 2)
            finally:
                server.shutdown()
                thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, "fixture.example")]
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
            .not_valid_after(datetime.now(UTC) + timedelta(minutes=5))
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName("fixture.example")]),
                False,
            )
            .sign(key, hashes.SHA256())
        )
        with tempfile.TemporaryDirectory() as folder:
            private = Path(folder) / "key.pem"
            public = Path(folder) / "certificate.pem"
            private.write_bytes(
                key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            private.chmod(0o600)
            public.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(public, private)
            server.socket = context.wrap_socket(
                server.socket, server_side=True
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            with patch.object(socket, "getaddrinfo", side_effect=owned_dns):
                try:
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        check_gateway.check("https://fixture.example", 2)
                finally:
                    server.shutdown()
                    thread.join(timeout=3)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
