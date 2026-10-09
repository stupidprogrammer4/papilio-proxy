"""Fetch checksum-pinned Linux amd64 binaries; never start a core."""

import argparse
import hashlib
import io
import os
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, model_validator


class TestCoreRelease(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    version: str
    url: HttpUrl
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    archive: Literal["zip", "tar.gz", "binary"]
    member: str | None

    @model_validator(mode="after")
    def valid_archive(self) -> "TestCoreRelease":
        if self.url.scheme != "https":
            raise ValueError("Core artifacts require HTTPS")
        if self.archive != "binary" and not self.member:
            raise ValueError("Archives require an explicit binary member")
        return self


def fetch(release: TestCoreRelease, destination: Path, timeout: float) -> None:
    with urllib.request.urlopen(str(release.url), timeout=timeout) as response:
        artifact = response.read()
    if hashlib.sha256(artifact).hexdigest() != release.sha256:
        raise ValueError(f"{release.name}: artifact checksum mismatch")
    if release.archive == "zip":
        assert release.member is not None
        with zipfile.ZipFile(io.BytesIO(artifact)) as archive:
            binary = archive.read(release.member)
    elif release.archive == "tar.gz":
        assert release.member is not None
        with tarfile.open(
            fileobj=io.BytesIO(artifact), mode="r:gz"
        ) as archive:
            member = archive.getmember(release.member)
            if not member.isfile():
                raise ValueError("The selected member must be a regular file")
            stream = archive.extractfile(member)
            assert stream is not None
            binary = stream.read()
    else:
        binary = artifact
    target = destination / release.name
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(descriptor, "wb") as output:
        output.write(binary)
    print(f"{release.name} {release.version}: checksum verified")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    releases = TypeAdapter(list[TestCoreRelease]).validate_json(
        args.manifest.read_text()
    )
    args.destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    for release in releases:
        fetch(release, args.destination, args.timeout)


if __name__ == "__main__":
    main()
