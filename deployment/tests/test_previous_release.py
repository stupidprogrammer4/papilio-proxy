"""Upgrade the published Django alpha and recover its backup on fresh owned state."""

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from deployment.papilio_installer.configuration import Installation
from deployment.papilio_installer.docker import Compose
from deployment.papilio_installer.releases import download_release
from deployment.tests.image_release import prebuilt_release
from deployment.tests.installer_terminal import safe_terminal_output

PROJECT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.installed,
    pytest.mark.skipif(
        os.environ.get("PAPILIO_RUN_PREVIOUS_RELEASE_TEST") != "1",
        reason="Opt in to public prior-version installation, upgrade and fresh-state recovery.",
    ),
]


def execute(arguments: list[str]) -> bytes:
    result = subprocess.run(arguments, capture_output=True, timeout=900)
    assert result.returncode == 0, safe_terminal_output(result.stderr)
    return result.stdout


def inspect_state(installation: Installation, statement: str) -> bytes:
    result = Compose(installation).run(
        "exec",
        "-T",
        "api",
        "python",
        "manage.py",
        "shell",
        "--no-imports",
        "-c",
        statement,
        capture=True,
    )
    return result.stdout.strip()


@pytest.mark.parametrize("previous_version", ["0.1.0-alpha.1", "0.1.0-alpha.2", "0.1.0-alpha.3"])
def test_published_alpha_upgrade_and_previous_backup_recovery(
    tmp_path: Path, previous_version: str
) -> None:
    old_source = download_release(tmp_path / "download", previous_version)
    instance = f"upgrade-{uuid4().hex[:10]}"
    homes = (tmp_path / "before", tmp_path / "recovered")
    identity = ["--environment", "sandbox", "--instance", instance]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    old_command = [sys.executable, str(old_source / "deployment/papilio.py")]
    previous_image_arguments = (
        ["--image-mode", "build"] if previous_version != "0.1.0-alpha.1" else []
    )
    installation = None
    try:
        with prebuilt_release(PROJECT, tmp_path) as candidate:
            assert candidate.bundle is not None and candidate.assets is not None
            cache = homes[0] / "cache/images"
            cache.mkdir(parents=True)
            shutil.copy2(candidate.assets / candidate.bundle.asset, cache)
            execute(
                [
                    *old_command,
                    "--home",
                    str(homes[0]),
                    *identity,
                    "install",
                    "--source",
                    str(old_source),
                    "--port",
                    str(port),
                    "--allow-unverified-host",
                    "--command-path",
                    str(tmp_path / "commands/old"),
                    *previous_image_arguments,
                ]
            )
            installation = Installation.load(homes[0] / "sandbox" / instance)
            original_values = installation.values.copy()
            inspect_state(
                installation,
                "from django.contrib.auth.models import User; "
                "User.objects.create_superuser('upgrade-owner', password='isolated-password-97!'); "
                "from django_celery_beat.models import PeriodicTask, IntervalSchedule; "
                "interval,_=IntervalSchedule.objects.get_or_create(every=17, period='seconds'); "
                "PeriodicTask.objects.filter(name__endswith='.outbox').update("
                "enabled=False, interval=interval); "
                "assert PeriodicTask.objects.filter(name__endswith='.outbox').exists()",
            )
            backup = tmp_path / "previous-backup.tar.gz"
            execute(
                [
                    *old_command,
                    "--home",
                    str(homes[0]),
                    *identity,
                    "backup",
                    "--output",
                    str(backup),
                ]
            )
            execute(
                [
                    "bash",
                    str(PROJECT / "install.sh"),
                    "--update",
                    "--source",
                    str(candidate.source),
                    "--home",
                    str(homes[0]),
                    *identity,
                    "--image-mode",
                    "prebuilt",
                    "--non-interactive",
                    "--allow-unverified-host",
                ]
            )
            installation = Installation.load(installation.root)
            assert installation.source == candidate.source
            assert installation.settings.image_mode == "prebuilt"
            assert installation.values == original_values
            check = (
                "from django.contrib.auth.models import User; "
                "owner=User.objects.get(username='upgrade-owner'); "
                "assert owner.is_superuser and owner.check_password('isolated-password-97!'); "
                "from django_celery_beat.models import PeriodicTask; "
                "schedule=PeriodicTask.objects.get(name__endswith='.outbox'); "
                "assert not schedule.enabled and schedule.interval.every == 17; "
                "print('retained-state')"
            )
            assert inspect_state(installation, check) == b"retained-state"
            version = inspect_state(
                installation,
                "from papilio_panel import __version__; print(__version__)",
            )
            assert version.decode() == candidate.bundle.version
            Compose(installation).run("down", "--remove-orphans")
            # Recovery uses the native same-version restore on a fresh old schema.
            # The upgraded state is retained in its own root; it is not downgraded in place.
            execute(
                [
                    *old_command,
                    "--home",
                    str(homes[1]),
                    *identity,
                    "install",
                    "--source",
                    str(old_source),
                    "--port",
                    str(port),
                    "--allow-unverified-host",
                    "--command-path",
                    str(tmp_path / "commands/recovered"),
                    *previous_image_arguments,
                ]
            )
            installation = Installation.load(homes[1] / "sandbox" / instance)
            execute([*old_command, "--home", str(homes[1]), *identity, "restore", str(backup)])
            installation = Installation.load(installation.root)
            assert (
                installation.values["PAPILIO_SECRET_KEY"] == original_values["PAPILIO_SECRET_KEY"]
            )
            assert inspect_state(installation, check) == b"retained-state"
            assert (
                inspect_state(
                    installation,
                    "from papilio_panel import __version__; print(__version__)",
                )
                == previous_version.encode()
            )
    finally:
        for home in homes:
            root = home / "sandbox" / instance
            if not (root / "installation.json").exists():
                continue
            installation = Installation.load(root)
            Compose(installation).run("down", "--remove-orphans")
            assert home.resolve().is_relative_to(tmp_path.resolve())
            execute(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network=none",
                    "--mount",
                    f"type=bind,src={home.resolve()},dst=/owned",
                    "python:3.13-slim-bookworm",
                    "python",
                    "-c",
                    f"import shutil; shutil.rmtree('/owned/sandbox/{instance}/state')",
                ]
            )
