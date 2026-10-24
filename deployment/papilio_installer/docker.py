"""Use native Compose lifecycle with the installation's private environment."""

import os
import subprocess
from typing import IO

from .configuration import Installation
from .images import (
    ImageBundle,
    ImageRole,
    docker_platform,
    download_image_bundle,
    inspect_image_bundle,
    load_image_bundle,
    read_image_bundle,
)


class Compose:
    def __init__(self, installation: Installation) -> None:
        self.installation = installation
        if installation.settings.local_node and not all(
            (installation.source / name).exists()
            for name in (
                "deployment/node.Dockerfile",
                "deployment/compose.local-node.yml",
                "panel/backend/src/papilio_panel/modules/local_nodes",
            )
        ):
            raise ValueError("This source has no bundled local runtime; choose --no-local-node.")
        self.bundle: ImageBundle | None = None
        if (
            installation.settings.image_mode != "build"
            and (installation.source / "deployment/images.json").exists()
        ):
            self.bundle = read_image_bundle(installation.source, docker_platform())
        if installation.settings.image_mode == "prebuilt" and self.bundle is None:
            raise ValueError("This source has no prebuilt image manifest; choose build explicitly.")
        if (
            installation.settings.local_node
            and self.bundle is not None
            and ImageRole.NODE not in {image.role for image in self.bundle.images}
        ):
            raise ValueError(
                "This release has no node image; choose --no-local-node or a newer release."
            )

    def run(
        self,
        *arguments: str,
        capture: bool = False,
        stdout: IO[bytes] | None = None,
        stdin: IO[bytes] | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        installation = self.installation
        command = [
            "docker",
            "compose",
            "--project-name",
            installation.settings.project,
            "--project-directory",
            str(installation.source),
            "--env-file",
            str(installation.root / "runtime.env"),
            "-f",
            str(installation.source / "deployment/compose.yml"),
        ]
        environment = os.environ | installation.values
        environment.pop("COMPOSE_PROFILES", None)
        if installation.settings.local_node:
            command.extend(
                [
                    "-f",
                    str(installation.source / "deployment/compose.local-node.yml"),
                    "--profile",
                    "local-node",
                ]
            )
        if self.bundle is not None:
            environment.update(
                {
                    f"PAPILIO_{image.role.value.upper()}_IMAGE": image.reference
                    for image in self.bundle.images
                }
            )
            environment["PAPILIO_PULL_POLICY"] = "never"
        environment["PAPILIO_PUBLIC_ORIGIN"] = installation.settings.origin
        environment["PAPILIO_TRANSPORT_SCHEME"] = installation.values.get(
            "PAPILIO_TRANSPORT_SCHEME", installation.settings.transport_scheme
        )
        if installation.settings.tls_enabled:
            command.extend(["-f", str(installation.source / "deployment/compose.production.yml")])
            environment["PAPILIO_SITE_ADDRESS"] += f", http://{installation.settings.host}"
        command.extend(arguments)
        result = subprocess.run(
            command,
            env=environment,
            check=True,
            stdout=subprocess.PIPE if capture else stdout,
            stdin=stdin,
        )
        return result

    def doctor(self, timeout: int = 120) -> None:
        self.run(
            "exec", "-T", "api", "python", "manage.py", "runtime_status", "--timeout", str(timeout)
        )

    def start(self) -> None:
        arguments = ["up", "-d", "--remove-orphans"]
        if self.bundle is not None:
            self.prepare_images()
            arguments.extend(["--no-build", "--pull", "never"])
        self.run(*arguments)
        self.doctor()

    def prepare_images(self) -> None:
        if self.bundle is None:
            self.run("build")
            return
        if not inspect_image_bundle(self.bundle):
            print(f"Loading verified release images: {self.bundle.asset}", flush=True)
            cache = self.installation.root.parent.parent / "cache/images"
            archive = download_image_bundle(self.bundle, cache)
            load_image_bundle(archive, self.bundle)

    def stop(self) -> None:
        self.run("stop", "--timeout", self.installation.values["PAPILIO_SHUTDOWN_SECONDS"])
