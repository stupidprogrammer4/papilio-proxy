"""Exercise the shipped CLI, real browser and PostgreSQL restore on owned resources."""

import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from deployment.papilio_installer.archives import backup, restore
from deployment.papilio_installer.cli import update
from deployment.papilio_installer.configuration import Installation
from deployment.papilio_installer.docker import Compose

pytestmark = [
    pytest.mark.installed,
    pytest.mark.skipif(
        os.environ.get("PAPILIO_RUN_INSTALLER_TESTS") != "1",
        reason="Opt in to creating a disposable full Compose installation.",
    ),
]
PROJECT = Path(__file__).resolve().parents[2]


def test_install_browser_backup_restore_and_restart_preserve_data(tmp_path: Path) -> None:
    home = tmp_path / "installation"
    instance = f"browser-{uuid4().hex[:10]}"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = [
        sys.executable,
        str(PROJECT / "deployment/papilio.py"),
        "--home",
        str(home),
        "--environment",
        "test",
        "--instance",
        instance,
    ]
    installation = None
    launcher = tmp_path / "commands/papilio"
    try:
        subprocess.run(
            [
                *command,
                "install",
                "--source",
                str(PROJECT),
                "--port",
                str(port),
                "--allow-unverified-host",
                "--command-path",
                str(launcher),
            ],
            check=True,
            capture_output=True,
            timeout=900,
        )
        installation = Installation.load(home / "test" / instance)
        compose = Compose(installation)
        token = (
            compose.run(
                "exec", "-T", "api", "python", "manage.py", "owner_setup_token", capture=True
            )
            .stdout.decode()
            .strip()
        )
        browser_environment = os.environ | {
            "PAPILIO_BROWSER_URL": f"http://127.0.0.1:{port}",
            "PAPILIO_SETUP_TOKEN": token,
            "PAPILIO_BROWSER_USERNAME": "browser-owner",
            "PAPILIO_BROWSER_PASSWORD": "isolated-browser-test-password-749!",
        }
        browser_result = subprocess.run(
            ["node", str(PROJECT / "panel/frontend/tests/foundation.browser.mjs")],
            env=browser_environment,
            capture_output=True,
            timeout=120,
        )
        browser_error = browser_result.stderr.decode().replace(token, "[setup token redacted]")
        browser_error = browser_error.replace(
            browser_environment["PAPILIO_BROWSER_PASSWORD"], "[test password redacted]"
        )
        assert browser_result.returncode == 0, browser_error
        role = compose.run(
            "exec",
            "-T",
            "postgres",
            "psql",
            "--username=papilio",
            "--dbname=papilio",
            "-At",
            "-c",
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole "
            "FROM pg_roles WHERE rolname=current_user",
            capture=True,
        )
        assert role.stdout.strip() == b"f"
        saved = tmp_path / "backup.tar.gz"
        backup(installation, saved)
        assert saved.stat().st_mode & 0o777 == 0o600
        compose.run(
            "exec",
            "-T",
            "api",
            "python",
            "manage.py",
            "shell",
            "--no-imports",
            "-c",
            "from django.contrib.auth.models import User; "
            "User.objects.create_user(username='after-backup')",
            capture=True,
        )
        restore(installation, saved, tmp_path / "before-restore.tar.gz")
        restored = Installation.load(installation.root)
        assert restored.values["PAPILIO_SECRET_KEY"] == installation.values["PAPILIO_SECRET_KEY"]
        compose.stop()
        compose.start()
        result = compose.run(
            "exec",
            "-T",
            "api",
            "python",
            "manage.py",
            "shell",
            "--no-imports",
            "-c",
            "from django.contrib.auth.models import User; "
            "assert User.objects.filter(username='browser-owner', is_superuser=True).exists(); "
            "assert not User.objects.filter(username='after-backup').exists(); "
            "from papilio_panel.modules.nodes.models import Node; "
            "from papilio_panel.modules.nodes.providers import nodes; "
            "n=Node.objects.get(name='browser-node'); "
            "assert n.runtime.request_timeout_seconds == 7; "
            "assert len(nodes.bootstrap(n.id, n.owner_id)) > 100; "
            "from django_celery_beat.models import PeriodicTask; "
            "schedule=PeriodicTask.objects.get(name__endswith='.node-outbox'); "
            "assert not schedule.enabled and schedule.interval.every == 9; "
            "print('independent-read-passed')",
            capture=True,
        )
        assert result.stdout.strip() == b"independent-read-passed"
        next_source = tmp_path / "next-release"
        for folder in ("deployment", "panel/backend", "panel/frontend"):
            shutil.copytree(
                PROJECT / folder,
                next_source / folder,
                ignore=shutil.ignore_patterns(
                    "node_modules",
                    "dist",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "graphify-out",
                ),
            )
        shutil.copy2(PROJECT / ".dockerignore", next_source / ".dockerignore")
        (next_source / "VERSION").write_text("0.1.0-alpha.2\n")
        version_file = next_source / "panel/backend/src/papilio_panel/__init__.py"
        version_file.write_text(version_file.read_text().replace("0.1.0-alpha.1", "0.1.0-alpha.2"))
        update(restored, next_source)
        upgraded = Installation.load(restored.root)
        assert upgraded.source == next_source
        assert str(next_source / "deployment/papilio.py") in launcher.read_text()
        assert upgraded.values == restored.values
        upgraded_state = Compose(upgraded).run(
            "exec",
            "-T",
            "api",
            "python",
            "manage.py",
            "shell",
            "--no-imports",
            "-c",
            "from papilio_panel import __version__; "
            "from django.contrib.auth.models import User; "
            "assert __version__ == '0.1.0-alpha.2'; "
            "assert User.objects.filter(username='browser-owner').exists(); "
            "from papilio_panel.modules.nodes.models import Node; "
            "assert Node.objects.get(name='browser-node').runtime.request_timeout_seconds == 7; "
            "from django_celery_beat.models import PeriodicTask; "
            "schedule=PeriodicTask.objects.get(name__endswith='.node-outbox'); "
            "assert not schedule.enabled and schedule.interval.every == 9; "
            "print('synthetic-upgrade-passed')",
            capture=True,
        )
        assert upgraded_state.stdout.strip() == b"synthetic-upgrade-passed"
    finally:
        root = home / "test" / instance
        if (root / "installation.json").exists():
            installation = Installation.load(root)
        if installation is not None:
            Compose(installation).run("down", "--remove-orphans")
            # Only this test's private bind-mounted state is removed, after its containers stop.
            assert home.resolve().is_relative_to(tmp_path.resolve())
            subprocess.run(
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
                    f"import shutil; shutil.rmtree('/owned/test/{instance}/state')",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
