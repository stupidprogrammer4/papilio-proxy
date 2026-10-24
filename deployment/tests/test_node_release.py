"""Publishing native node bundles binds both platforms to the selected release."""

import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from test_image_package import package_fixture
from test_node_artifacts import candidate

PROJECT = Path(__file__).resolve().parents[2]


def node_assets(directory: Path, version: str) -> Path:
    directory.mkdir()
    for architecture in ("amd64", "arm64"):
        path = candidate(directory / f"papilio-node-{version}-linux-{architecture}.tar.gz")
        with tarfile.open(path) as archive:
            contents = {}
            for member in archive:
                content = archive.extractfile(member)
                assert content is not None
                with content:
                    contents[member.name] = content.read()
        manifest = json.loads(contents["manifest.json"])
        manifest["version"] = version
        manifest["platform"] = f"linux/{architecture}"
        if architecture == "arm64":
            for name in ("bin/xray", "bin/papilio-agent"):
                value = bytearray(contents[name])
                value[18:20] = (183).to_bytes(2, "little")
                contents[name] = bytes(value)
                manifest["files"][name]["sha256"] = hashlib.sha256(contents[name]).hexdigest()
        contents["manifest.json"] = json.dumps(manifest).encode()
        with tarfile.open(path, "w:gz") as archive:
            for name, value in contents.items():
                member = tarfile.TarInfo(name)
                member.size = len(value)
                archive.addfile(member, io.BytesIO(value))
    return directory


@pytest.mark.parametrize("missing", [False, True])
def test_node_bundles_are_verified_and_included_in_release_checksums(
    tmp_path: Path, missing: bool
) -> None:
    source, images = package_fixture(tmp_path)
    version = (source / "VERSION").read_text().strip()
    nodes = node_assets(tmp_path / "nodes", version)
    if missing:
        (nodes / f"papilio-node-{version}-linux-arm64.tar.gz").unlink()
    output = tmp_path / "release"
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "deployment/package_release.py"),
            "--source",
            str(source),
            "--images",
            str(images),
            "--nodes",
            str(nodes),
            "--output",
            str(output),
            "--tag",
            f"v{version}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if missing:
        assert result.returncode != 0
        assert "required node platform bundle is missing" in result.stderr
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        checksums = {
            name: digest
            for digest, name in (
                line.split() for line in (output / "SHA256SUMS").read_text().splitlines()
            )
        }
        for architecture in ("amd64", "arm64"):
            name = f"papilio-node-{version}-linux-{architecture}.tar.gz"
            assert checksums[name] == hashlib.sha256((output / name).read_bytes()).hexdigest()
