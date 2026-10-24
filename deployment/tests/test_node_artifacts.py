"""Candidate bundles reject unbound executables and unsafe archive paths."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from deployment.papilio_installer.node.artifacts import inspect_bundle
from deployment.papilio_installer.node.packaging import write_bundle


def elf(machine: int = 62) -> bytes:
    value = bytearray(64)
    value[:6] = b"\x7fELF\x02\x01"
    value[18:20] = machine.to_bytes(2, "little")
    return bytes(value)


def candidate(path: Path, *, name: str = "bin/xray", binary: bytes | None = None) -> Path:
    files = {
        "bin/papilio-agent": elf(),
        name: elf() if binary is None else binary,
        "licenses/Papilio-MIT.txt": b"MIT fixture",
        "licenses/Xray-MPL-2.0.txt": b"MPL fixture",
        "licenses/Go-dependencies.txt": b"Controlled dependency notices fixture",
    }
    manifest = {
        "format": 1,
        "version": "0.1.0-alpha.4",
        "platform": "linux/amd64",
        "xray_version": "26.3.27",
        "files": {
            name: {"sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
            for name, content in files.items()
        },
    }
    files["manifest.json"] = json.dumps(manifest).encode()
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


def test_verified_bundle_declares_matching_native_platform_and_owned_members(
    tmp_path: Path,
) -> None:
    bundle = inspect_bundle(candidate(tmp_path / "bundle.tgz"), "linux/amd64")
    assert bundle.version == "0.1.0-alpha.4"
    assert bundle.xray_version == "26.3.27"
    assert set(bundle.files) == {
        "bin/papilio-agent",
        "bin/xray",
        "licenses/Papilio-MIT.txt",
        "licenses/Xray-MPL-2.0.txt",
        "licenses/Go-dependencies.txt",
    }


@pytest.mark.parametrize("name", ["../xray", "/bin/xray", "bin/xray/../../outside"])
def test_unsafe_bundle_paths_are_rejected_before_writes(tmp_path: Path, name: str) -> None:
    source = candidate(tmp_path / "bundle.tgz", name=name)
    with pytest.raises(ValueError):
        inspect_bundle(source, "linux/amd64")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bundle.tgz"]


@pytest.mark.parametrize("binary", [b"#!/bin/sh\necho untrusted", elf(183)])
def test_binary_headers_must_match_the_selected_linux_architecture(
    tmp_path: Path, binary: bytes
) -> None:
    with pytest.raises(ValueError):
        inspect_bundle(candidate(tmp_path / "bundle.tgz", binary=binary), "linux/amd64")


def test_platform_mismatch_and_configured_size_limit_reject_bundle(tmp_path: Path) -> None:
    source = candidate(tmp_path / "bundle.tgz")
    with pytest.raises(ValueError):
        inspect_bundle(source, "linux/arm64")
    with pytest.raises(ValueError):
        inspect_bundle(source, "linux/amd64", byte_limit=1)


def test_link_and_duplicate_members_are_rejected(tmp_path: Path) -> None:
    source = candidate(tmp_path / "original.tgz")
    for mode in ("link", "duplicate"):
        target = tmp_path / f"{mode}.tgz"
        with tarfile.open(source) as original, tarfile.open(target, "w:gz") as archive:
            for member in original:
                archive.addfile(member, original.extractfile(member))
            extra = tarfile.TarInfo("bin/xray")
            if mode == "link":
                extra.type = tarfile.SYMTYPE
                extra.linkname = "/etc/passwd"
            archive.addfile(extra)
        with pytest.raises(ValueError):
            inspect_bundle(target, "linux/amd64")


def test_packager_never_deletes_an_existing_destination(tmp_path: Path) -> None:
    binary = tmp_path / "agent"
    binary.write_bytes(elf())
    notice = tmp_path / "license"
    notice.write_text("Controlled fixture license")
    destination = tmp_path / "existing.tgz"
    destination.write_bytes(b"retain existing release")
    with pytest.raises(FileExistsError):
        write_bundle(
            destination, "0.1.0-alpha.4", "linux/amd64", binary, binary, notice, notice, notice
        )
    assert destination.read_bytes() == b"retain existing release"
