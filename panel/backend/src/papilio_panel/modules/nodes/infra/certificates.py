"""Native per-node X.509 issuance for CPU workers."""

from datetime import timedelta
from ipaddress import ip_address

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from django.utils import timezone

from ..domain import CertificateInput, CredentialPrivateKeys, IssuedCredentials


def private_pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def certificate_pem(certificate: x509.Certificate) -> str:
    return certificate.public_bytes(serialization.Encoding.PEM).decode()


class NativeCertificateIssuer:
    def issue(self, values: CertificateInput) -> IssuedCredentials:
        now = timezone.now()
        before = now - timedelta(seconds=values.policy.backdate_seconds)
        expires = now + timedelta(seconds=values.policy.validity_seconds)
        authority_key = Ed25519PrivateKey.generate()
        server_key = Ed25519PrivateKey.generate()
        control_key = Ed25519PrivateKey.generate()
        authority_name = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, f"Papilio node {values.node_id}")]
        )
        authority = (
            x509.CertificateBuilder()
            .subject_name(authority_name)
            .issuer_name(
                authority_name,
            )
            .public_key(authority_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(
                before,
            )
            .not_valid_after(now + timedelta(seconds=values.policy.authority_validity_seconds))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(authority_key, algorithm=None)
        )
        prefix = f"spiffe://papilio/{values.deployment_id}/nodes/{values.node_id}"
        try:
            hostname: x509.GeneralName = x509.IPAddress(ip_address(values.hostname))
        except ValueError:
            hostname = x509.DNSName(values.hostname)
        server = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Papilio node agent")]),
            )
            .issuer_name(authority_name)
            .public_key(server_key.public_key())
            .serial_number(
                x509.random_serial_number(),
            )
            .not_valid_before(before)
            .not_valid_after(expires)
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        hostname,
                        x509.UniformResourceIdentifier(prefix + "/agent"),
                    ]
                ),
                critical=False,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=True,
            )
            .sign(authority_key, algorithm=None)
        )
        control = (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Papilio node control")]),
            )
            .issuer_name(authority_name)
            .public_key(control_key.public_key())
            .serial_number(
                x509.random_serial_number(),
            )
            .not_valid_before(before)
            .not_valid_after(expires)
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.UniformResourceIdentifier(prefix + "/control"),
                    ]
                ),
                critical=False,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
                critical=True,
            )
            .sign(authority_key, algorithm=None)
        )
        return IssuedCredentials(
            authority_certificate=certificate_pem(authority),
            server_certificate=certificate_pem(server),
            control_certificate=certificate_pem(control),
            private_keys=CredentialPrivateKeys(
                authority=private_pem(authority_key),
                server=private_pem(server_key),
                control=private_pem(control_key),
            ),
            expires_at=expires,
        )
