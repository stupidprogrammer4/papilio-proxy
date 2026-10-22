"""Verify native Docker bundle load/inspect on unique test-owned image references."""

import gzip
import hashlib
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from deployment.papilio_installer.configuration import Installation, InstallSettings, encode_env
from deployment.papilio_installer.images import (
    ImageBundle,
    ImageReference,
    ImageRole,
    docker_platform,
    image_asset_name,
    image_reference,
    inspect_image_bundle,
    load_image_bundle,
)

pytestmark = [
    pytest.mark.installed,
    pytest.mark.skipif(
        os.environ.get("PAPILIO_RUN_INSTALLER_TESTS") != "1",
        reason="Opt in to building/loading only unique test-owned Docker images.",
    ),
]


@pytest.mark.parametrize("environment", ["sandbox", "production"])
def test_legacy_bootstrap_environment_still_accepts_next_compose(
    tmp_path: Path, environment: str
) -> None:
    source = Path(__file__).resolve().parents[2]
    installation = Installation.create(tmp_path, source, InstallSettings(environment=environment))
    legacy = installation.values.copy()
    legacy.pop("PAPILIO_TRANSPORT_SCHEME")
    (installation.root / "runtime.env").write_text(encode_env(legacy))
    env = os.environ | legacy
    env.pop("PAPILIO_TRANSPORT_SCHEME", None)
    env.pop("PAPILIO_PUBLIC_ORIGIN", None)
    command = [
        "docker",
        "compose",
        "--project-directory",
        str(source),
        "--env-file",
        str(installation.root / "runtime.env"),
        "-f",
        str(source / "deployment/compose.yml"),
    ]
    if environment == "production":
        command.extend(["-f", str(source / "deployment/compose.production.yml")])
    result = subprocess.run([*command, "config", "--quiet"], env=env, capture_output=True)
    assert result.returncode == 0, result.stderr.decode()


def test_native_load_verifies_all_image_identities_and_rejects_corruption(tmp_path: Path) -> None:
    version = f"0.0.0-test.{uuid4().hex}"
    platform = docker_platform()
    references = tuple(image_reference(role, version, platform) for role in ImageRole)
    context = tmp_path / "context"
    context.mkdir()
    (context / "marker").write_text(version)
    (context / "Dockerfile").write_text("FROM scratch\nCOPY marker /marker\n")
    tags = [argument for reference in references for argument in ("--tag", reference)]
    subprocess.run(
        ["docker", "build", *tags, str(context)], check=True, capture_output=True, timeout=90
    )
    try:
        backend = image_reference(ImageRole.BACKEND, version, platform)
        content_id = subprocess.check_output(
            ["docker", "image", "inspect", "--format", "{{.Id}}", backend],
            text=True,
        ).strip()
        # One native multi-tag build establishes all references for the same content ID.
        images = tuple(
            ImageReference(role, image_reference(role, version, platform), content_id)
            for role in ImageRole
        )
        uncompressed = tmp_path / "images.tar"
        subprocess.run(
            ["docker", "image", "save", "--output", str(uncompressed), *references],
            check=True,
            capture_output=True,
            timeout=30,
        )
        archive = tmp_path / image_asset_name(version, platform)
        with uncompressed.open("rb") as source, gzip.open(archive, "wb", compresslevel=1) as output:
            shutil.copyfileobj(source, output)
        bundle = ImageBundle(
            version,
            platform,
            archive.name,
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            archive.stat().st_size,
            images,
        )
        assert inspect_image_bundle(bundle)
        subprocess.run(
            ["docker", "image", "rm", "--force", *references],
            check=True,
            capture_output=True,
            timeout=30,
        )
        assert not inspect_image_bundle(bundle)
        corrupted = tmp_path / "corrupted.tar.gz"
        corrupted.write_bytes(b"not-a-verified-image-archive")
        with pytest.raises(ValueError, match="checksum|size"):
            load_image_bundle(corrupted, bundle)
        assert not inspect_image_bundle(bundle)
        load_image_bundle(archive, bundle)
        assert inspect_image_bundle(bundle)
        wrong_images = tuple(
            replace(image, content_id="sha256:" + "f" * 64)
            if image.role == ImageRole.BACKEND
            else image
            for image in images
        )
        wrong_bundle = replace(bundle, images=wrong_images)
        assert not inspect_image_bundle(wrong_bundle)
    finally:
        subprocess.run(
            ["docker", "image", "rm", "--force", *references],
            check=False,
            capture_output=True,
            timeout=30,
        )
