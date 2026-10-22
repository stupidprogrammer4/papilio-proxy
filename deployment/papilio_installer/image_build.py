"""Build and export the fixed native service images for one release/platform."""

import gzip
import hashlib
import json
import shutil
import subprocess
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
        "format": 1,
        "version": bundle.version,
        "platforms": {
            bundle.platform: {
                "asset": bundle.asset,
                "sha256": bundle.sha256,
                "size": bundle.size,
                "images": [
                    {"role": image.role.value, "reference": image.reference, "id": image.content_id}
                    for image in bundle.images
                ],
            }
        },
    }


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
        version, platform, asset.name, digest.hexdigest(), asset.stat().st_size, tuple(images)
    )
    metadata = output / f"images-{platform.replace('/', '-')}.json"
    metadata.write_text(json.dumps(bundle_manifest(bundle), indent=2) + "\n")
    return bundle
