"""Packaged source must bind both public image bundles to the verified current commit."""

import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
VERSION = "0.1.0-alpha.2"
ROLES = ("backend", "frontend", "postgres", "redis", "rabbitmq")


def package_fixture(tmp_path: Path, *, node_runtime: bool = False) -> tuple[Path, Path]:
    source = tmp_path / "source"
    settings = source / "panel/backend/src/papilio_panel/config/settings.py"
    settings.parent.mkdir(parents=True)
    settings.write_text("# Controlled packaging fixture, not an executable backend.\n")
    (source / "VERSION").write_text(VERSION + "\n")
    (source / "README.md").write_text("Tracked source fixture.\n")
    tracked = ["VERSION", "README.md", str(settings.relative_to(source))]
    if node_runtime:
        node = source / "deployment/node.Dockerfile"
        node.parent.mkdir()
        node.write_text("# Controlled source declaring a node runtime image.\n")
        tracked.append("deployment/node.Dockerfile")
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    subprocess.run(
        ["git", "add", *tracked],
        cwd=source,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Packaging fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "Controlled current source",
        ],
        cwd=source,
        check=True,
    )
    (source / "WORK.md").write_text("Local record excluded from the source archive.\n")
    assets = tmp_path / "assets"
    assets.mkdir()
    for arch in ("amd64", "arm64"):
        body = f"controlled external image bytes for {arch}".encode()
        asset = assets / f"papilio-{VERSION}-images-linux-{arch}.tar.gz"
        asset.write_bytes(body)
        manifest = {
            "format": 2,
            "version": VERSION,
            "platforms": {
                f"linux/{arch}": {
                    "asset": asset.name,
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "size": len(body),
                    "images": [
                        {
                            "role": role,
                            "reference": f"papilio/{role}:{VERSION}-{arch}",
                            "id": "sha256:" + str(index) * 64,
                            "config_id": "sha256:" + "f" * 64,
                        }
                        for index, role in enumerate(ROLES, 1)
                    ],
                }
            },
        }
        (assets / f"images-linux-{arch}.json").write_text(json.dumps(manifest))
    return source, assets


def run_package(source: Path, assets: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(PROJECT / "deployment/package_release.py"),
            "--source",
            str(source),
            "--images",
            str(assets),
            "--output",
            str(output),
            "--tag",
            f"v{VERSION}",
        ],
        capture_output=True,
        text=True,
    )


def test_source_archive_contains_verified_both_platform_manifests_and_no_local_records(
    tmp_path: Path,
) -> None:
    source, assets = package_fixture(tmp_path)
    output = tmp_path / "output"
    result = run_package(source, assets, output)
    assert result.returncode == 0, result.stderr
    archive_path = output / f"papilio-{VERSION}.tar.gz"
    with tarfile.open(archive_path) as archive:
        member = archive.extractfile(f"papilio-{VERSION}/deployment/images.json")
        assert member is not None
        manifest = json.load(member)
        assert set(manifest["platforms"]) == {"linux/amd64", "linux/arm64"}
        assert not any(name.endswith("/WORK.md") for name in archive.getnames())
    checksums = {
        name: digest
        for digest, name in (
            line.split() for line in (output / "SHA256SUMS").read_text().splitlines()
        )
    }
    assert checksums[archive_path.name] == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert len(checksums) == 3


@pytest.mark.parametrize("fault", ["missing_platform", "checksum", "version"])
def test_incomplete_or_inconsistent_image_artifacts_cannot_publish(
    tmp_path: Path, fault: str
) -> None:
    source, assets = package_fixture(tmp_path)
    if fault == "missing_platform":
        (assets / "images-linux-arm64.json").unlink()
    elif fault == "checksum":
        (assets / f"papilio-{VERSION}-images-linux-amd64.tar.gz").write_bytes(b"corrupt")
    else:
        metadata = assets / "images-linux-amd64.json"
        body = json.loads(metadata.read_text())
        body["version"] = "0.1.0-alpha.3"
        metadata.write_text(json.dumps(body))
    output = tmp_path / "output"
    result = run_package(source, assets, output)
    assert result.returncode != 0
    reason = {"missing_platform": "platform", "checksum": "checksum", "version": "version"}[fault]
    assert reason in result.stderr.lower()
    assert not (output / "SHA256SUMS").exists()


def test_classic_only_image_metadata_cannot_be_published_as_portable(tmp_path: Path) -> None:
    source, assets = package_fixture(tmp_path)
    for arch in ("amd64", "arm64"):
        metadata = assets / f"images-linux-{arch}.json"
        manifest = json.loads(metadata.read_text())
        manifest["format"] = 1
        for bundle in manifest["platforms"].values():
            for identity in bundle["images"]:
                identity.pop("config_id", None)
        metadata.write_text(json.dumps(manifest))
    result = run_package(source, assets, tmp_path / "output")
    assert result.returncode != 0
    assert "portable" in result.stderr.lower()


@pytest.mark.parametrize("mixed", [False, True])
def test_packaged_node_images_preserve_format_and_reject_mixed_platform_contracts(
    tmp_path: Path,
    mixed: bool,
) -> None:
    source, assets = package_fixture(tmp_path, node_runtime=True)
    for arch in ("amd64", "arm64"):
        if mixed and arch == "arm64":
            continue
        metadata = assets / f"images-linux-{arch}.json"
        manifest = json.loads(metadata.read_text())
        manifest["format"] = 3
        manifest["platforms"][f"linux/{arch}"]["images"].append(
            {
                "role": "node",
                "reference": f"papilio/node:{VERSION}-{arch}",
                "id": "sha256:" + "6" * 64,
                "config_id": "sha256:" + "f" * 64,
            }
        )
        metadata.write_text(json.dumps(manifest))
    output = tmp_path / "output"
    result = run_package(source, assets, output)
    if mixed:
        assert result.returncode != 0 and "format" in result.stderr.lower()
        assert not (output / "SHA256SUMS").exists()
    else:
        assert result.returncode == 0, result.stderr
        with tarfile.open(output / f"papilio-{VERSION}.tar.gz") as archive:
            stream = archive.extractfile(f"papilio-{VERSION}/deployment/images.json")
            assert stream is not None
            manifest = json.load(stream)
        assert manifest["format"] == 3
        for bundle in manifest["platforms"].values():
            assert {row["role"] for row in bundle["images"]} == {*ROLES, "node"}


def test_source_with_node_runtime_cannot_publish_a_legacy_five_image_bundle(
    tmp_path: Path,
) -> None:
    source, assets = package_fixture(tmp_path, node_runtime=True)
    output = tmp_path / "output"
    result = run_package(source, assets, output)
    assert result.returncode != 0 and "node" in result.stderr.lower()
    assert not (output / "SHA256SUMS").exists()
