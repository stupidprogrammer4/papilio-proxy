"""Use native Compose lifecycle with the installation's private environment."""

import os
import subprocess
from typing import IO

from .configuration import Installation


class Compose:
    def __init__(self, installation: Installation) -> None:
        self.installation = installation

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
        if installation.settings.environment == "production":
            command.extend(["-f", str(installation.source / "deployment/compose.production.yml")])
        command.extend(arguments)
        result = subprocess.run(
            command,
            env=os.environ | installation.values,
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
        self.run("up", "-d", "--remove-orphans")
        self.doctor()

    def stop(self) -> None:
        self.run("stop", "--timeout", self.installation.values["PAPILIO_SHUTDOWN_SECONDS"])
