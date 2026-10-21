"""Track ownership of the installed command without replacing unrelated files."""

import hashlib
import json
import os
import shlex
import tempfile
from pathlib import Path

from .configuration import Installation, replace_private


class ManagedLauncher:
    def __init__(self, installation: Installation) -> None:
        self.installation = installation
        self.path: Path | None = None

    def prepare(self, requested: Path | None = None, *, allow_alias: bool = False) -> None:
        metadata = json.loads((self.installation.root / "installation.json").read_text())
        record = metadata.get("launcher")
        path = requested.absolute() if requested else None
        if record:
            owned = Path(record["path"])
            if path is not None and path != owned:
                raise ValueError("This installation already owns a different command path.")
            if owned.is_symlink() or not owned.is_file():
                raise ValueError("The managed command is missing or was modified.")
            digest = hashlib.sha256(owned.read_bytes()).hexdigest()
            if digest != record["sha256"]:
                raise ValueError("The managed command was modified; preserve or move it first.")
            path = owned
        elif path is not None and (path.exists() or path.is_symlink()):
            if allow_alias and path.name == "papilio":
                settings = self.installation.settings
                path = path.with_name(f"papilio-{settings.instance}-{settings.environment}")
            if path.exists() or path.is_symlink():
                raise ValueError("The command path is not owned by this installation.")
        self.path = path

    def write(self, source: Path) -> None:
        if self.path is None:
            return
        command = [
            "python3",
            str(source / "deployment/papilio.py"),
            "--home",
            str(self.installation.root.parent.parent),
            "--environment",
            self.installation.settings.environment,
            "--instance",
            self.installation.settings.instance,
        ]
        content = "#!/bin/sh\nexec " + shlex.join(command) + ' "$@"\n'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path = self.installation.root / "installation.json"
        metadata = json.loads(metadata_path.read_text())
        owned = metadata.get("launcher") is not None
        with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        try:
            temporary.chmod(0o755)
            if owned:
                self.prepare()
                os.replace(temporary, self.path)
            else:
                # Atomic creation must refuse a destination created since preflight.
                os.link(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        metadata["launcher"] = {
            "path": str(self.path),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
        replace_private(metadata_path, json.dumps(metadata, indent=2) + "\n")
        print(f"Installed command: {self.path}")
