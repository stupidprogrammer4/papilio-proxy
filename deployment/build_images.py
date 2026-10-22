#!/usr/bin/env python3
"""Release image builder composition root; publishing is owned by the release workflow."""

import argparse
from pathlib import Path

from papilio_installer.image_build import build_image_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    bundle = build_image_bundle(arguments.source, arguments.output)
    print(f"Verified native image identities: {bundle.version} / {bundle.platform}")


if __name__ == "__main__":
    main()
