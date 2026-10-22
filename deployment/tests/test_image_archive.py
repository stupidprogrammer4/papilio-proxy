"""Portable metadata uses the config and OCI bytes from native export archives."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from deployment.papilio_installer.image_build import portable_image_identities
from deployment.papilio_installer.images import ImageReference, ImageRole, image_reference


def exported_fixture(
    tmp_path: Path, fault: str | None = None
) -> tuple[Path, tuple[ImageReference, ...], str, str]:
    config = b'{"architecture":"amd64","os":"linux"}'
    config_id = "sha256:" + hashlib.sha256(config).hexdigest()
    config_path = "blobs/sha256/" + config_id.removeprefix("sha256:")
    descriptor = json.dumps({"config": {"digest": config_id}}).encode()
    native_id = "sha256:" + hashlib.sha256(descriptor).hexdigest()
    images = tuple(
        ImageReference(role, image_reference(role, "0.0.0-test", "linux/amd64"), native_id)
        for role in ImageRole
    )
    archive = tmp_path / "native.tar"
    contents = {
        "oci-layout": b'{"imageLayoutVersion":"1.0.0"}',
        "manifest.json": json.dumps(
            [{"Config": config_path, "RepoTags": [image.reference for image in images]}]
        ).encode(),
        config_path: config,
        "blobs/sha256/" + native_id.removeprefix("sha256:"): descriptor,
    }
    native_path = "blobs/sha256/" + native_id.removeprefix("sha256:")
    if fault == "config_digest":
        contents[config_path] = b"changed native configuration"
    elif fault == "oci_digest":
        contents[native_path] = b"changed native OCI descriptor"
    elif fault == "missing_blob":
        contents.pop(native_path)
    elif fault == "layout":
        contents["oci-layout"] = b'{"imageLayoutVersion":"unsupported"}'
    elif fault == "duplicate":
        entry = {"Config": config_path, "RepoTags": [image.reference for image in images]}
        contents["manifest.json"] = json.dumps([entry, entry]).encode()
    with tarfile.open(archive, "w") as output:
        for name, content in contents.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            output.addfile(info, io.BytesIO(content))
    return archive, images, config_id, native_id


def test_exported_config_and_oci_digests_are_bound_to_each_reference(tmp_path: Path) -> None:
    archive, images, config_id, native_id = exported_fixture(tmp_path)
    portable = portable_image_identities(archive, images)
    assert {image.reference for image in portable} == {image.reference for image in images}
    assert all(image.config_id == config_id and image.content_id == native_id for image in portable)


def test_classic_export_is_rejected_before_portable_publication(tmp_path: Path) -> None:
    archive = tmp_path / "classic.tar"
    with tarfile.open(archive, "w"):
        pass
    with pytest.raises(ValueError, match="OCI|containerd"):
        portable_image_identities(archive, ())


@pytest.mark.parametrize(
    "fault", ["config_digest", "oci_digest", "missing_blob", "layout", "duplicate"]
)
def test_invalid_native_archive_metadata_never_becomes_a_portable_identity(
    tmp_path: Path, fault: str
) -> None:
    archive, images, _, _ = exported_fixture(tmp_path, fault)
    with pytest.raises(ValueError):
        portable_image_identities(archive, images)
