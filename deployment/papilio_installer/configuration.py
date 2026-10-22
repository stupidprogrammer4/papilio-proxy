"""Validated installation identity and private bootstrap configuration."""

import json
import os
import re
import secrets
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

ENVIRONMENTS = ("dev", "test", "sandbox", "production")
NATIVE_ENVIRONMENT_KEYS = {
    "DATABASE_URL",
    "CELERY_BROKER_URL",
    "POSTGRES_PASSWORD",
    "RABBITMQ_DEFAULT_USER",
    "RABBITMQ_DEFAULT_PASS",
    "REDISCLI_AUTH",
}


def validate_environment_key(key: str) -> None:
    if not key.startswith("PAPILIO_") and key not in NATIVE_ENVIRONMENT_KEYS:
        raise ValueError("Only Papilio bootstrap environment keys are accepted.")


@dataclass(frozen=True)
class InstallSettings:
    environment: str = "sandbox"
    instance: str = "default"
    host: str = "panel.example.com"
    bind_address: str = "127.0.0.1"
    http_port: int = 8080
    https_port: int = 8443
    scheme: str | None = None
    image_mode: str = "auto"

    @classmethod
    def from_options(
        cls,
        *,
        environment: str,
        instance: str = "default",
        host: str = "localhost",
        scheme: str | None = None,
        bind_address: str | None = None,
        http_port: int | None = None,
        https_port: int | None = None,
        image_mode: str = "auto",
    ) -> "InstallSettings":
        production = environment == "production"
        return cls(
            environment=environment,
            instance=instance,
            host=host,
            scheme=scheme,
            image_mode=image_mode,
            bind_address=bind_address
            if bind_address is not None
            else ("0.0.0.0" if production else "127.0.0.1"),
            http_port=http_port if http_port is not None else (80 if production else 8080),
            https_port=https_port if https_port is not None else (443 if production else 8443),
        )

    @property
    def transport_scheme(self) -> str:
        return self.scheme or ("https" if self.environment == "production" else "http")

    @property
    def tls_enabled(self) -> bool:
        return self.transport_scheme == "https"

    @property
    def origin(self) -> str:
        port = self.https_port if self.tls_enabled else self.http_port
        return f"{self.transport_scheme}://{self.host}:{port}"

    @property
    def project(self) -> str:
        return f"papilio-{self.instance}-{self.environment}"

    def matches(self, other: "InstallSettings") -> bool:
        return replace(self, scheme=self.transport_scheme) == replace(
            other, scheme=other.transport_scheme
        )

    def validate(self) -> None:
        if self.image_mode not in {"auto", "prebuilt", "build"}:
            raise ValueError("Choose auto, prebuilt or build as the image mode.")
        if self.scheme is not None and self.scheme not in {"http", "https"}:
            raise ValueError("Choose http or https as the transport scheme.")
        if self.environment not in ENVIRONMENTS:
            raise ValueError("Choose dev, test, sandbox or production.")
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", self.instance) is None:
            raise ValueError("The instance must be a lowercase identifier of up to 40 characters.")
        if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}", self.host) is None:
            raise ValueError("The host must be a hostname or IPv4 address without a URL path.")
        if self.bind_address not in {"127.0.0.1", "0.0.0.0"}:
            raise ValueError("Choose 127.0.0.1 or 0.0.0.0 as the bind address.")
        if not all(
            isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535
            for port in (self.http_port, self.https_port)
        ):
            raise ValueError("A port must be between 1 and 65535.")
        if self.tls_enabled and self.http_port == self.https_port:
            raise ValueError("HTTP and HTTPS require different ports.")


def load_settings(path: Path) -> InstallSettings:
    try:
        settings = InstallSettings(**json.loads(path.read_text()))
        settings.validate()
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(
            "The installation settings file has an invalid shape or field type."
        ) from error
    return settings


def write_private(path: Path, value: str) -> None:
    """Create a private file atomically without a world-readable creation window."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(value)


def replace_private(path: Path, value: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        output.write(value)
        output.flush()
        os.fsync(output.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def encode_env(values: dict[str, str]) -> str:
    lines = []
    for key, value in values.items():
        validate_environment_key(key)
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None or "\n" in value or "\r" in value:
            raise ValueError("Invalid bootstrap environment entry.")
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"{key}='{escaped}'")
    return "\n".join(lines) + "\n"


def decode_env(content: str) -> dict[str, str]:
    values = {}
    for line in content.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, raw = line.partition("=")
        if not separator or re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is None:
            raise ValueError("Invalid runtime.env entry.")
        validate_environment_key(key)
        if key in values:
            raise ValueError("Duplicate runtime.env entry.")
        value = raw.strip()
        if value.startswith("'") and value.endswith("'"):
            value = value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
        values[key] = value
    return values


@dataclass(frozen=True)
class Installation:
    root: Path
    source: Path
    settings: InstallSettings
    values: dict[str, str]

    def persist_settings(self) -> None:
        metadata_path = self.root / "installation.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["settings"] = asdict(self.settings)
        replace_private(metadata_path, json.dumps(metadata, indent=2) + "\n")

    @classmethod
    def create(cls, home: Path, source: Path, settings: InstallSettings) -> "Installation":
        settings.validate()
        root = home.resolve() / settings.environment / settings.instance
        root.mkdir(parents=True, mode=0o700, exist_ok=False)
        source = source.resolve()
        database_password = secrets.token_urlsafe(36)
        redis_password = secrets.token_urlsafe(36)
        broker_password = secrets.token_urlsafe(36)
        values = {
            "PAPILIO_ENV": settings.environment,
            "PAPILIO_INSTANCE": settings.instance,
            "PAPILIO_SECRET_KEY": secrets.token_urlsafe(64),
            "PAPILIO_ALLOWED_HOSTS": f"{settings.host},localhost,127.0.0.1",
            "PAPILIO_TRUSTED_ORIGINS": settings.origin,
            "PAPILIO_TRANSPORT_SCHEME": settings.transport_scheme,
            "PAPILIO_BEHIND_PROXY": "true",
            "PAPILIO_DB_PASSWORD": database_password,
            "POSTGRES_PASSWORD": secrets.token_urlsafe(36),
            "DATABASE_URL": f"postgresql://papilio:{database_password}@postgres:5432/papilio",
            "PAPILIO_CACHE_URL": f"redis://:{redis_password}@redis:6379/0",
            "PAPILIO_REDIS_PASSWORD": redis_password,
            "REDISCLI_AUTH": redis_password,
            "CELERY_BROKER_URL": f"amqp://papilio:{broker_password}@rabbitmq:5672//",
            "RABBITMQ_DEFAULT_USER": "papilio",
            "RABBITMQ_DEFAULT_PASS": broker_password,
            "PAPILIO_PROJECT": settings.project,
            "PAPILIO_STATE_ROOT": str(root / "state"),
            "PAPILIO_ENV_FILE": str(root / "runtime.env"),
            "PAPILIO_BIND_ADDRESS": settings.bind_address,
            "PAPILIO_HTTP_PORT": str(settings.http_port),
            "PAPILIO_HTTPS_PORT": str(settings.https_port),
            "PAPILIO_SITE_ADDRESS": settings.host if settings.tls_enabled else ":80",
            "PAPILIO_WEB_WORKERS": "2",
            "PAPILIO_SHUTDOWN_SECONDS": "120",
        }
        metadata = {"format": 1, "source": str(source), "settings": asdict(settings)}
        write_private(root / "installation.json", json.dumps(metadata, indent=2) + "\n")
        write_private(root / "runtime.env", encode_env(values))
        (root / "state").mkdir(mode=0o700)
        return cls(root=root, source=source, settings=settings, values=values)

    @classmethod
    def load(cls, root: Path) -> "Installation":
        metadata = json.loads((root / "installation.json").read_text())
        if metadata["format"] != 1:
            raise ValueError("Unsupported installation format.")
        settings = InstallSettings(**metadata["settings"])
        settings.validate()
        values = decode_env((root / "runtime.env").read_text())
        identity = {
            "PAPILIO_ENV": settings.environment,
            "PAPILIO_INSTANCE": settings.instance,
            "PAPILIO_PROJECT": settings.project,
            "PAPILIO_STATE_ROOT": str(root.resolve() / "state"),
            "PAPILIO_ENV_FILE": str(root.resolve() / "runtime.env"),
        }
        if any(values.get(key) != value for key, value in identity.items()):
            raise ValueError(
                "Runtime state paths and namespace must match the installation identity."
            )
        return cls(
            root=root.resolve(), source=Path(metadata["source"]), settings=settings, values=values
        )
