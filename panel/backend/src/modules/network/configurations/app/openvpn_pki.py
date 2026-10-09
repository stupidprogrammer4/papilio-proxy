import secrets
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from src.modules.network.configurations.domain.openvpn import (
    OpenVpnCertificate,
    OpenVpnClientCertificate,
    OpenVpnKeyType,
    OpenVpnOptions,
    OpenVpnPkiMaterial,
    OpenVpnServerMaterial,
)

OpenVpnPrivateKey = ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey


class OpenVpnCertificateAuthority:
    @staticmethod
    def private_key(kind: OpenVpnKeyType) -> OpenVpnPrivateKey:
        if kind == "ec_p256":
            return ec.generate_private_key(ec.SECP256R1())
        bits = {"rsa_2048": 2048, "rsa_3072": 3072, "rsa_4096": 4096}[kind]
        return rsa.generate_private_key(public_exponent=65537, key_size=bits)

    @staticmethod
    def private_pem(key: OpenVpnPrivateKey) -> str:
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii")

    @staticmethod
    def load_private(value: str | None) -> OpenVpnPrivateKey:
        if value is None:
            raise ValueError("The certificate signing key is unavailable")
        key = serialization.load_pem_private_key(value.encode("ascii"), None)
        if not isinstance(
            key, (ec.EllipticCurvePrivateKey, rsa.RSAPrivateKey)
        ):
            raise ValueError("Unsupported OpenVPN signing key")
        return key

    def create(self, options: OpenVpnOptions) -> OpenVpnPkiMaterial:
        now = datetime.now(UTC)
        authority_key = self.private_key(options.key_type)
        subject = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, options.ca_name)]
        )
        authority = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(authority_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=options.ca_validity_days))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0), critical=True
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
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
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(
                    authority_key.public_key()
                ),
                critical=False,
            )
            .sign(authority_key, hashes.SHA256())
        )
        server_key = self.private_key(options.key_type)
        server = self.leaf(
            authority,
            authority_key,
            server_key,
            options.server_name,
            options.server_validity_days,
            ExtendedKeyUsageOID.SERVER_AUTH,
            now,
        )
        tls_crypt_key = None
        if options.tls_crypt:
            encoded = secrets.token_hex(256)
            lines = [
                encoded[index : index + 64]
                for index in range(0, len(encoded), 64)
            ]
            tls_crypt_key = "\n".join(
                [
                    "-----BEGIN OpenVPN Static key V1-----",
                    *lines,
                    "-----END OpenVPN Static key V1-----",
                    "",
                ]
            )
        return OpenVpnPkiMaterial(
            ca_certificate=authority.public_bytes(
                serialization.Encoding.PEM
            ).decode("ascii"),
            ca_private_key=self.private_pem(authority_key),
            server_certificate=server.public_bytes(
                serialization.Encoding.PEM
            ).decode("ascii"),
            server_private_key=self.private_pem(server_key),
            tls_crypt_key=tls_crypt_key,
        )

    @staticmethod
    def leaf(
        authority: x509.Certificate,
        authority_key: OpenVpnPrivateKey,
        key: OpenVpnPrivateKey,
        identity: str,
        days: int,
        purpose: x509.ObjectIdentifier,
        now: datetime,
    ) -> x509.Certificate:
        expiry = min(now + timedelta(days=days), authority.not_valid_after_utc)
        if expiry <= now:
            raise ValueError("The certificate authority has expired")
        return (
            x509.CertificateBuilder()
            .subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, identity)])
            )
            .issuer_name(authority.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(expiry)
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=isinstance(key, rsa.RSAPrivateKey),
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([purpose]), critical=False)
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    authority_key.public_key()
                ),
                critical=False,
            )
            .sign(authority_key, hashes.SHA256())
        )

    def issue(
        self,
        options: OpenVpnOptions,
        material: OpenVpnPkiMaterial,
        identity: str,
    ) -> OpenVpnClientCertificate:
        now = datetime.now(UTC)
        authority = x509.load_pem_x509_certificate(
            material.ca_certificate.encode("ascii")
        )
        key = self.private_key(options.key_type)
        certificate = self.leaf(
            authority,
            self.load_private(material.ca_private_key),
            key,
            identity,
            options.client_validity_days,
            ExtendedKeyUsageOID.CLIENT_AUTH,
            now,
        )
        return OpenVpnClientCertificate(
            certificate=certificate.public_bytes(
                serialization.Encoding.PEM
            ).decode("ascii"),
            private_key=self.private_pem(key),
            serial=str(certificate.serial_number),
        )

    def revocations(
        self,
        material: OpenVpnPkiMaterial,
        certificates: list[OpenVpnClientCertificate],
        validity_seconds: int,
    ) -> str:
        now = datetime.now(UTC)
        authority = x509.load_pem_x509_certificate(
            material.ca_certificate.encode("ascii")
        )
        until = min(
            now + timedelta(seconds=validity_seconds),
            authority.not_valid_after_utc,
        )
        if until <= now:
            raise ValueError("The certificate authority has expired")
        builder = (
            x509.CertificateRevocationListBuilder()
            .issuer_name(authority.subject)
            .last_update(now)
            .next_update(until)
        )
        serials: set[int] = set()
        for stored in certificates:
            certificate = x509.load_pem_x509_certificate(
                stored.certificate.encode("ascii")
            )
            certificate.verify_directly_issued_by(authority)
            if str(certificate.serial_number) != stored.serial:
                raise ValueError(
                    "Stored certificate serial does not match its certificate"
                )
            if certificate.serial_number in serials:
                continue
            serials.add(certificate.serial_number)
            revoked = (
                x509.RevokedCertificateBuilder()
                .serial_number(certificate.serial_number)
                .revocation_date(now)
                .build()
            )
            builder = builder.add_revoked_certificate(revoked)
        result = builder.sign(
            self.load_private(material.ca_private_key), hashes.SHA256()
        )
        return result.public_bytes(serialization.Encoding.PEM).decode("ascii")

    @staticmethod
    def client_valid(
        material: OpenVpnServerMaterial,
        stored: OpenVpnCertificate,
        identity: str,
        now: datetime,
    ) -> bool:
        current = now.replace(tzinfo=UTC) if now.tzinfo is None else now
        try:
            authority = x509.load_pem_x509_certificate(
                material.ca_certificate.encode("ascii")
            )
            certificate = x509.load_pem_x509_certificate(
                stored.certificate.encode("ascii")
            )
            certificate.verify_directly_issued_by(authority)
            subjects = certificate.subject.get_attributes_for_oid(
                NameOID.COMMON_NAME
            )
            purpose = certificate.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            ).value
            return (
                authority.not_valid_before_utc
                <= current
                < authority.not_valid_after_utc
                and certificate.not_valid_before_utc
                <= current
                < certificate.not_valid_after_utc
                and str(certificate.serial_number) == stored.serial
                and len(subjects) == 1
                and subjects[0].value == identity
                and ExtendedKeyUsageOID.CLIENT_AUTH in purpose
            )
        except (ValueError, InvalidSignature, x509.ExtensionNotFound):
            return False

    @staticmethod
    def server_valid(
        material: OpenVpnServerMaterial, name: str, now: datetime
    ) -> bool:
        current = now.replace(tzinfo=UTC) if now.tzinfo is None else now
        try:
            authority = x509.load_pem_x509_certificate(
                material.ca_certificate.encode("ascii")
            )
            server = x509.load_pem_x509_certificate(
                material.server_certificate.encode("ascii")
            )
            server.verify_directly_issued_by(authority)
            subjects = server.subject.get_attributes_for_oid(
                NameOID.COMMON_NAME
            )
            purpose = server.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            ).value
            key = OpenVpnCertificateAuthority.load_private(
                material.server_private_key
            )
            return (
                authority.not_valid_before_utc
                <= current
                < authority.not_valid_after_utc
                and server.not_valid_before_utc
                <= current
                < server.not_valid_after_utc
                and len(subjects) == 1
                and subjects[0].value == name
                and ExtendedKeyUsageOID.SERVER_AUTH in purpose
                and key.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
                == server.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
        except (ValueError, InvalidSignature, x509.ExtensionNotFound):
            return False
