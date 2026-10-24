"""Unit lifecycle check: external Docker command double, actual OS exec failure."""

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from deployment.papilio_installer.configuration import Installation, InstallSettings
from deployment.papilio_installer.docker import Compose
from deployment.tests.local_node_client import published_client_traffic


def test_external_origin_is_removed_when_the_native_client_cannot_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installation = Installation.create(
        tmp_path / "home", Path.cwd(), InstallSettings(image_mode="build")
    )
    binary = tmp_path / "installed-xray-client"
    binary.write_bytes(b"this-is-not-an-executable-format")
    binary.chmod(0o700)
    commands: list[list[str]] = []

    def external_command(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"external-origin-double", b"")

    monkeypatch.setattr(subprocess, "run", external_command)
    with pytest.raises(OSError):
        published_client_traffic(
            Compose(installation), tmp_path, f"vless://{uuid4()}@127.0.0.1:18444"
        )
    removals = [command for command in commands if "rm" in command and "--force" in command]
    assert len(removals) == 1
    created_names = {
        value
        for command in commands
        for value in command
        if value.startswith("papilio-test-origin-")
    }
    assert len(created_names) == 1
    assert created_names.issubset(set(removals.pop()))
