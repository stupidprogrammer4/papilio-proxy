"""Exercise installer form contracts and actual ncurses terminal interaction."""

import json
import os
import signal
import sys
from pathlib import Path

import pytest
from deployment.papilio_installer.configuration import Installation, InstallSettings
from deployment.papilio_installer.tui import ConfigurationForm
from deployment.tests.installer_terminal import (
    read_until,
    resize_terminal,
    safe_terminal_output,
    wizard_process,
)


@pytest.mark.parametrize("environment", ["dev", "test", "sandbox", "production"])
def test_form_preserves_explicit_configuration(environment: str) -> None:
    initial = InstallSettings(
        environment=environment,
        instance="operator",
        host="panel.test",
        scheme="http",
        bind_address="0.0.0.0",
        http_port=9080,
        https_port=9443,
        image_mode="prebuilt",
    )
    form = ConfigurationForm.from_settings(initial)
    assert form.settings() == initial
    form.scheme.value = "https"
    assert form.settings().http_port == 9080
    assert form.settings().https_port == 9443
    form.scheme.value = "http"
    assert form.settings() == initial


def test_invalid_form_keeps_the_draft_for_correction() -> None:
    form = ConfigurationForm.from_settings(InstallSettings(host="panel.test"))
    form.http_port.value = "0"
    with pytest.raises(ValueError, match="port"):
        form.settings()
    assert form.http_port.value == "0"
    assert form.host.value == "panel.test"
    form.http_port.value = "9080"
    assert form.settings().http_port == 9080


def test_terminal_failure_diagnostics_redact_grants_and_connection_credentials() -> None:
    grant = "A" * 43
    output = (
        "\x1b[31mConnection failed\x1b[0m postgres://operator:short-secret@postgres/db\n"
        f"{grant}\nPermission denied"
    )
    diagnostic = safe_terminal_output(output.encode())
    assert grant not in diagnostic and "short-secret" not in diagnostic
    assert "Permission denied" in diagnostic and "Connection failed" in diagnostic
    assert "\x1b" not in diagnostic


def test_real_terminal_edits_transport_and_keeps_advanced_values(tmp_path: Path) -> None:
    output = tmp_path / "settings.json"
    with wizard_process(output) as (terminal, process):
        read_until(terminal, b"PAPILIO")
        # Tab to the transport choice, cycle HTTPS -> HTTP, then review (Ctrl-R).
        os.write(terminal, b"\x01\x01\t\t \x12")
        read_until(terminal, b"Review")
        os.write(terminal, b"\n")
        assert process.wait(timeout=5) == 0
    settings = InstallSettings(**json.loads(output.read_text()))
    assert settings.scheme == "http"
    assert settings.instance == "demo"
    assert settings.http_port == 9080 and settings.https_port == 9443
    assert output.stat().st_mode & 0o777 == 0o600


def test_real_terminal_resize_and_cancel_leaves_no_configuration(tmp_path: Path) -> None:
    output = tmp_path / "settings.json"
    with wizard_process(output) as (terminal, process):
        read_until(terminal, b"PAPILIO")
        resize_terminal(terminal, 12, 40)
        process.send_signal(signal.SIGWINCH)
        read_until(terminal, b"Resize")
        resize_terminal(terminal, 24, 96)
        process.send_signal(signal.SIGWINCH)
        read_until(terminal, b"PAPILIO")
        os.write(terminal, b"q")
        assert process.wait(timeout=5) == 130
    assert not output.exists()


def test_advanced_terminal_requires_room_for_all_fields_and_retains_choices(tmp_path: Path) -> None:
    output = tmp_path / "settings.json"
    with wizard_process(output) as (terminal, process):
        read_until(terminal, b"PAPILIO")
        resize_terminal(terminal, 22, 96)
        process.send_signal(signal.SIGWINCH)
        os.write(terminal, b"\x01")
        read_until(terminal, b"Resize")
        resize_terminal(terminal, 24, 96)
        process.send_signal(signal.SIGWINCH)
        read_until(terminal, b"VPN client port")
        os.write(terminal, b"\x12")
        read_until(terminal, b"Review")
        os.write(terminal, b"\n")
        assert process.wait(timeout=5) == 0
    settings = InstallSettings(**json.loads(output.read_text()))
    assert settings.local_node is True and settings.node_port == 8444


def test_plain_terminal_fallback_uses_same_settings_contract(tmp_path: Path) -> None:
    output = tmp_path / "settings.json"
    with wizard_process(output, term="dumb") as (terminal, process):
        read_until(terminal, b"PAPILIO")
        os.write(terminal, b"\n" * 11)
        assert process.wait(timeout=5) == 0
    assert InstallSettings(**json.loads(output.read_text())).scheme == "https"


def test_real_terminal_keeps_invalid_host_until_corrected(tmp_path: Path) -> None:
    output = tmp_path / "settings.json"
    with wizard_process(output) as (terminal, process):
        read_until(terminal, b"PAPILIO")
        os.write(terminal, b"\t\n\x15../escape\n\x12")
        read_until(terminal, b"hostname")
        assert not output.exists()
        os.write(terminal, b"\n\x15chosen.example.com\n\x12")
        read_until(terminal, b"Review")
        os.write(terminal, b"\n")
        assert process.wait(timeout=5) == 0
    assert json.loads(output.read_text())["host"] == "chosen.example.com"


def test_real_terminal_seeds_saved_instance_without_changing_secrets(tmp_path: Path) -> None:
    saved = Installation.create(
        tmp_path / "home",
        Path.cwd(),
        InstallSettings(
            environment="dev",
            host="saved.example.com",
            scheme="http",
            instance="existing",
            http_port=9081,
            https_port=9445,
        ),
    )
    output = tmp_path / "settings.json"
    command = [
        sys.executable,
        "-m",
        "papilio_installer.tui",
        "--existing-root",
        str(saved.root),
        "--output",
        str(output),
    ]
    with wizard_process(output, command=command) as (terminal, process):
        read_until(terminal, b"PAPILIO")
        os.write(terminal, b"\x12")
        read_until(terminal, b"Review")
        os.write(terminal, b"\n")
        assert process.wait(timeout=5) == 0
    assert InstallSettings(**json.loads(output.read_text())) == saved.settings
    assert Installation.load(saved.root).values == saved.values
