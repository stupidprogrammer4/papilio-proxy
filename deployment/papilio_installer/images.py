"""Validate release-owned native image bundles before any download or Docker change."""

import hashlib
import http.client
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .releases import REPOSITORY, release_version

PLATFORMS = {"linux/amd64", "linux/arm64"}


class ImageRole(str, Enum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    POSTGRES = "postgres"
    REDIS = "redis"
    RABBITMQ = "rabbitmq"


@dataclass(frozen=True)
class ImageReference:
    role: ImageRole
    reference: str
    content_id: str
    config_id: str | None = None


@dataclass(frozen=True)
class ImageBundle:
    version: str
    platform: str
    asset: str
    sha256: str
    size: int
    images: tuple[ImageReference, ...]
    format_version: int = 1


@dataclass(frozen=True)
class InspectedImage:
    content_id: str
    platform: str
    references: frozenset[str]


def image_reference(role: ImageRole, version: str, platform: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError("The release has no supported image platform for this Docker daemon.")
    arch = platform.removeprefix("linux/")
    return f"papilio/{role.value}:{release_version(version)}-{arch}"


def image_asset_name(version: str, platform: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError("The image archive platform is not supported.")
    return f"papilio-{release_version(version)}-images-{platform.replace('/', '-')}.tar.gz"


def read_reference(
    value: object, version: str, platform: str, format_version: int
) -> ImageReference:
    if not isinstance(value, dict):
        raise ValueError("An image identity must be an object.")
    try:
        role = ImageRole(value.get("role"))
    except (ValueError, TypeError) as error:
        raise ValueError("The release manifest contains an unknown image role.") from error
    reference = value.get("reference")
    content_id = value.get("id")
    if not isinstance(reference, str) or reference != image_reference(role, version, platform):
        raise ValueError("The image reference is not owned by this release and platform.")
    if not isinstance(content_id, str) or re.fullmatch(r"sha256:[a-f0-9]{64}", content_id) is None:
        raise ValueError("The release image identity is invalid.")
    config_id = None
    if format_version == 2:
        config_id = value.get("config_id")
        if (
            not isinstance(config_id, str)
            or re.fullmatch(r"sha256:[a-f0-9]{64}", config_id) is None
            or config_id == content_id
        ):
            raise ValueError("A portable image requires distinct native OCI and config digests.")
    return ImageReference(role, reference, content_id, config_id)


def read_image_bundle(source: Path, platform: str) -> ImageBundle | None:
    path = source / "deployment/images.json"
    if not path.exists():
        return None
    if platform not in PLATFORMS:
        raise ValueError("This image platform is not supported by the release.")
    try:
        manifest = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError("The release image manifest is not valid JSON.") from error
    if not isinstance(manifest, dict) or type(manifest.get("format")) is not int:
        raise ValueError("The release image manifest has an invalid format.")
    if manifest["format"] not in {1, 2}:
        raise ValueError("The release image manifest format is not supported.")
    version = release_version((source / "VERSION").read_text().strip())
    if manifest.get("version") != version:
        raise ValueError("The image manifest version does not match this source release.")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or not isinstance(platforms.get(platform), dict):
        raise ValueError("The release image manifest has no bundle for this platform.")
    bundle = platforms[platform]
    asset = bundle.get("asset")
    if asset != image_asset_name(version, platform):
        raise ValueError("The image archive name does not match this release and platform.")
    checksum = bundle.get("sha256")
    if not isinstance(checksum, str) or re.fullmatch(r"[a-f0-9]{64}", checksum) is None:
        raise ValueError("The image archive checksum is invalid.")
    size = bundle.get("size")
    if type(size) is not int or not 0 < size <= 9223372036854775807:
        raise ValueError("The image archive size must be a positive integer.")
    raw_images = bundle.get("images")
    if not isinstance(raw_images, list):
        raise ValueError("The release image identities must be a list.")
    images = tuple(
        read_reference(value, version, platform, manifest["format"]) for value in raw_images
    )
    if len(images) != len(ImageRole) or {image.role for image in images} != set(ImageRole):
        raise ValueError("The release must declare each infrastructure image role exactly once.")
    return ImageBundle(version, platform, asset, checksum, size, images, manifest["format"])


def archive_matches(path: Path, bundle: ImageBundle) -> bool:
    if path.is_symlink():
        raise ValueError("An image cache entry must not be a symbolic link.")
    if not path.is_file() or path.stat().st_size != bundle.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == bundle.sha256


def download_image_bundle(
    bundle: ImageBundle, cache: Path, *, base_url: str | None = None, timeout: int = 60
) -> Path:
    if bundle.asset != image_asset_name(bundle.version, bundle.platform):
        raise ValueError("The image cache filename does not belong to this release.")
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = cache / bundle.asset
    if archive_matches(destination, bundle):
        return destination
    base = base_url or f"https://github.com/{REPOSITORY}/releases/download/v{bundle.version}"
    request = urllib.request.Request(
        f"{base.rstrip('/')}/{bundle.asset}", headers={"User-Agent": "Papilio-installer"}
    )
    with tempfile.NamedTemporaryFile(dir=cache, prefix=".image-download-", delete=False) as output:
        temporary = Path(output.name)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != bundle.size:
                    raise ValueError("The image archive transfer size does not match the release.")
                digest = hashlib.sha256()
                received = 0
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    received += len(block)
                    if received > bundle.size:
                        raise ValueError("The image archive exceeds its declared release size.")
                    output.write(block)
                    digest.update(block)
            if received != bundle.size or digest.hexdigest() != bundle.sha256:
                raise ValueError("The image archive size or checksum does not match the release.")
            output.flush()
            os.fsync(output.fileno())
            os.replace(temporary, destination)
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            raise OSError("The image archive transfer failed; retry the installation.") from error
        finally:
            temporary.unlink(missing_ok=True)
    return destination


def docker_platform() -> str:
    result = subprocess.run(
        ["docker", "info", "--format", "{{.OSType}}/{{.Architecture}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    operating_system, _, architecture = result.stdout.strip().partition("/")
    architecture = {"x86_64": "amd64", "aarch64": "arm64"}.get(architecture, architecture)
    platform = f"{operating_system}/{architecture}"
    if platform not in PLATFORMS:
        raise ValueError("The Docker daemon is outside the release's supported image platforms.")
    return platform


def read_inspected_image(value: object) -> InspectedImage | None:
    if not isinstance(value, dict):
        return None
    content_id = value.get("Id")
    operating_system = value.get("Os")
    architecture = value.get("Architecture")
    if not isinstance(content_id, str):
        return None
    if not isinstance(operating_system, str) or not isinstance(architecture, str):
        return None
    tags = value.get("RepoTags")
    if tags is None:
        tags = []
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        return None
    return InspectedImage(content_id, f"{operating_system}/{architecture}", frozenset(tags))


def read_native_images(references: tuple[str, ...]) -> tuple[InspectedImage, ...]:
    result = subprocess.run(
        ["docker", "image", "inspect", *references],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ()
    if not isinstance(payload, list):
        return ()
    images = []
    for value in payload:
        image = read_inspected_image(value)
        if image is None:
            return ()
        images.append(image)
    return tuple(images)


def inspect_image_bundle(bundle: ImageBundle) -> bool:
    images = read_native_images(tuple(image.reference for image in bundle.images))
    by_reference: dict[str, InspectedImage] = {}
    for image in images:
        for reference in image.references:
            previous = by_reference.get(reference)
            if previous is not None and previous != image:
                return False
            by_reference[reference] = image
    return all(
        by_reference.get(expected.reference) is not None
        and by_reference[expected.reference].content_id in {expected.content_id, expected.config_id}
        and by_reference[expected.reference].platform == bundle.platform
        for expected in bundle.images
    )


def load_image_bundle(archive: Path, bundle: ImageBundle) -> None:
    if not archive_matches(archive, bundle):
        raise ValueError("The image archive size or checksum does not match this release.")
    subprocess.run(["docker", "image", "load", "--input", str(archive)], check=True)
    if not inspect_image_bundle(bundle):
        raise ValueError("The loaded image identities do not match this release and platform.")
