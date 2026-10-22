"""Build an isolated current-source release without including other workspace edits."""

import io
import json
import os
import shutil
import subprocess
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from deployment.papilio_installer.image_build import build_image_bundle, bundle_manifest
from deployment.papilio_installer.images import (
    ImageBundle,
    ImageRole,
    archive_matches,
    docker_platform,
    image_reference,
    read_image_bundle,
)


@dataclass(frozen=True)
class PreparedRelease:
    source: Path
    bundle: ImageBundle | None = None
    assets: Path | None = None


@contextmanager
def prebuilt_release(project: Path, directory: Path) -> Iterator[PreparedRelease]:
    source = directory / "release-source"
    source.mkdir()
    current = subprocess.check_output(["git", "archive", "HEAD"], cwd=project)
    with tarfile.open(fileobj=io.BytesIO(current)) as archive:
        archive.extractall(source, filter="data")
    # Only the active installer work is overlaid; preserved frontend edits are excluded.
    shutil.copytree(
        project / "deployment",
        source / "deployment",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", ".ruff_cache", "graphify-out"
        ),
    )
    shutil.copy2(project / "install.sh", source / "install.sh")
    previous_version = (source / "VERSION").read_text().strip()
    supplied_assets = os.environ.get("PAPILIO_TEST_RELEASE_IMAGES")
    version = previous_version if supplied_assets else f"0.0.0-native.{uuid4().hex}"
    (source / "VERSION").write_text(version + "\n")
    version_file = source / "panel/backend/src/papilio_panel/__init__.py"
    version_file.write_text(version_file.read_text().replace(previous_version, version))
    platform = docker_platform()
    references = tuple(image_reference(role, version, platform) for role in ImageRole)
    try:
        if supplied_assets:
            assets = Path(supplied_assets).resolve()
            shutil.copy2(
                assets / f"images-{platform.replace('/', '-')}.json",
                source / "deployment/images.json",
            )
            bundle = read_image_bundle(source, platform)
            if bundle is None or not archive_matches(assets / bundle.asset, bundle):
                raise ValueError("The supplied release image archive is missing or corrupt.")
        else:
            assets = directory / "image-assets"
            bundle = build_image_bundle(source, assets)
            (source / "deployment/images.json").write_text(json.dumps(bundle_manifest(bundle)))
        for name in ("backend.Dockerfile", "frontend.Dockerfile"):
            (source / "deployment" / name).write_text("FROM scratch\nRUN exit 97\n")
        if not supplied_assets:
            subprocess.run(
                ["docker", "image", "rm", "--force", *references],
                check=True,
                capture_output=True,
                timeout=30,
            )
        yield PreparedRelease(source, bundle, assets)
    finally:
        if not supplied_assets:
            subprocess.run(
                ["docker", "image", "rm", "--force", *references],
                check=False,
                capture_output=True,
                timeout=30,
            )
