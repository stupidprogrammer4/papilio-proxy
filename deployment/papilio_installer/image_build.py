"""Build and export the fixed native service images for one release/platform."""

import gzip
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import replace
from pathlib import Path

from .configuration import Installation, InstallSettings
from .docker import Compose
from .images import (
    ImageBundle,
    ImageReference,
    ImageRole,
    docker_platform,
    image_asset_name,
    image_reference,
    read_native_images,
)
from .releases import release_version

DEPENDENCY_SERVICES = {
    ImageRole.POSTGRES: "postgres",
    ImageRole.REDIS: "redis",
    ImageRole.RABBITMQ: "rabbitmq",
}


def bundle_manifest(bundle: ImageBundle) -> dict[str, object]:
    return {
        "format": bundle.format_version,
        "version": bundle.version,
        "platforms": {
            bundle.platform: {
                "asset": bundle.asset,
                "sha256": bundle.sha256,
                "size": bundle.size,
                "images": [
                    {"role": image.role.value, "reference": image.reference, "id": image.content_id}
                    | ({"config_id": image.config_id} if image.config_id is not None else {})
                    for image in bundle.images
                ],
            }
        },
    }


def archive_blob_digest(archive: tarfile.TarFile, name: str) -> str:
    """Hash a regular native OCI blob without loading it into memory."""
    try:
        member = archive.getmember(name)
    except KeyError as error:
        raise ValueError("The native OCI image metadata blob is missing.") from error
    if not member.isfile():
        raise ValueError("Native image metadata must contain regular blobs.")
    blob = archive.extractfile(member)
    if blob is None:
        raise ValueError("The native image blob is missing.")
    digest = hashlib.sha256()
    with blob:
        for block in iter(lambda: blob.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def portable_image_identities(
    path: Path, images: tuple[ImageReference, ...]
) -> tuple[ImageReference, ...]:
    """Bind each named image to its exported OCI and configuration digests."""
    with tarfile.open(path) as archive:
        names = set(archive.getnames())
        if "oci-layout" not in names or "manifest.json" not in names:
            raise ValueError(
                "Portable releases require native OCI export; enable containerd image storage."
            )
        layout_file = archive.extractfile("oci-layout")
        if layout_file is None:
            raise ValueError("The native OCI layout metadata is missing.")
        with layout_file:
            layout = json.load(layout_file)
        if not isinstance(layout, dict) or layout.get("imageLayoutVersion") != "1.0.0":
            raise ValueError("The native OCI archive layout is not supported.")
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise ValueError("The native image manifest is missing.")
        with manifest_file:
            manifest = json.load(manifest_file)
        if not isinstance(manifest, list):
            raise ValueError("The native image manifest must contain explicit image records.")
        references = {image.reference for image in images}
        configs: dict[str, str] = {}
        for entry in manifest:
            if not isinstance(entry, dict) or not isinstance(entry.get("RepoTags"), list):
                raise ValueError("The native image reference list is invalid.")
            if not all(isinstance(reference, str) for reference in entry["RepoTags"]):
                raise ValueError("The native image reference list is invalid.")
            selected = references.intersection(entry["RepoTags"])
            if not selected:
                continue
            config_path = entry.get("Config")
            if not isinstance(config_path, str):
                raise ValueError("The native config blob path is invalid.")
            config_id = archive_blob_digest(archive, config_path)
            if config_path != "blobs/sha256/" + config_id.removeprefix("sha256:"):
                raise ValueError("The native config blob does not match its content digest.")
            for reference in selected:
                if reference in configs:
                    raise ValueError("The native export has duplicate image references.")
                configs[reference] = config_id
        portable = []
        for image in images:
            config_id = configs.get(image.reference)
            native_blob = "blobs/sha256/" + image.content_id.removeprefix("sha256:")
            if config_id is None or config_id == image.content_id:
                raise ValueError(
                    "Portable releases require distinct native OCI and config identities."
                )
            if archive_blob_digest(archive, native_blob) != image.content_id:
                raise ValueError("The native OCI descriptor does not match its content digest.")
            portable.append(replace(image, config_id=config_id))
    return tuple(portable)


def build_image_bundle(source: Path, output: Path) -> ImageBundle:
    source = source.resolve()
    version = release_version((source / "VERSION").read_text().strip())
    platform = docker_platform()
    output.mkdir(parents=True, exist_ok=True)
    asset = output / image_asset_name(version, platform)
    if asset.exists():
        raise FileExistsError("An image bundle for this release/platform already exists.")
    references = {role: image_reference(role, version, platform) for role in ImageRole}
    with tempfile.TemporaryDirectory(prefix="papilio-image-build-") as temporary:
        installation = Installation.create(
            Path(temporary), source, InstallSettings(environment="test", image_mode="build")
        )
        installation = replace(
            installation,
            values=installation.values
            | {
                "PAPILIO_BACKEND_IMAGE": references[ImageRole.BACKEND],
                "PAPILIO_FRONTEND_IMAGE": references[ImageRole.FRONTEND],
            },
        )
        compose = Compose(installation)
        configuration = json.loads(compose.run("config", "--format", "json", capture=True).stdout)
        compose.run("build", "api", "gateway")
        compose.run("pull", *DEPENDENCY_SERVICES.values())
        # Three fixed infrastructure services; native Docker has no multi-image tag command.
        for role, service in DEPENDENCY_SERVICES.items():
            original = configuration["services"][service]["image"]
            subprocess.run(["docker", "image", "tag", original, references[role]], check=True)
    native_images = read_native_images(tuple(references.values()))
    native_by_reference = {
        reference: image for image in native_images for reference in image.references
    }
    images = []
    for role, reference in references.items():
        image = native_by_reference.get(reference)
        if image is None or image.platform != platform:
            raise ValueError("A built image is missing or has the wrong native platform.")
        images.append(ImageReference(role, reference, image.content_id))
    with tempfile.TemporaryDirectory(dir=output) as temporary:
        uncompressed = Path(temporary) / "images.tar"
        subprocess.run(
            ["docker", "image", "save", "--output", str(uncompressed), *references.values()],
            check=True,
        )
        portable = portable_image_identities(uncompressed, tuple(images))
        with (
            uncompressed.open("rb") as original,
            gzip.open(asset, "xb", compresslevel=3) as compressed,
        ):
            shutil.copyfileobj(original, compressed, length=1024 * 1024)
    digest = hashlib.sha256()
    with asset.open("rb") as original:
        for block in iter(lambda: original.read(1024 * 1024), b""):
            digest.update(block)
    bundle = ImageBundle(
        version, platform, asset.name, digest.hexdigest(), asset.stat().st_size, portable, 2
    )
    metadata = output / f"images-{platform.replace('/', '-')}.json"
    metadata.write_text(json.dumps(bundle_manifest(bundle), indent=2) + "\n")
    return bundle
