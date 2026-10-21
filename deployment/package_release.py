#!/usr/bin/env python3
"""Package only the verified current commit, without local or uncommitted files."""

import argparse
import gzip
import hashlib
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = (root / "VERSION").read_text().strip()
    if arguments.tag != f"v{version}":
        raise ValueError("Release tag must match VERSION.")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=root, check=True)
    # This source path belongs to the new Django implementation only.
    subprocess.run(
        ["git", "cat-file", "-e", "HEAD:panel/backend/src/papilio_panel/config/settings.py"],
        cwd=root,
        check=True,
    )
    arguments.output.mkdir(parents=True, exist_ok=True)
    archive = arguments.output / f"papilio-{version}.tar.gz"
    with (
        archive.open("xb") as output,
        gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed,
    ):
        result = subprocess.run(
            ["git", "archive", "--format=tar", f"--prefix=papilio-{version}/", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
        )
        compressed.write(result.stdout)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (arguments.output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n")
    print(f"Packaged {archive.name} from the verified commit.")


if __name__ == "__main__":
    main()
