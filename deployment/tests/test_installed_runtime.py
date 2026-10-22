"""Exercise the shipped CLI, real browser and PostgreSQL restore on owned resources."""

import http.client
import json
import os
import select
import shutil
import socket
import ssl
import subprocess
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.request import urlopen
from uuid import uuid4

import pytest
from deployment.papilio_installer.archives import backup, restore
from deployment.papilio_installer.configuration import Installation
from deployment.papilio_installer.docker import Compose
from deployment.tests.image_release import PreparedRelease, prebuilt_release
from deployment.tests.installer_terminal import read_until, safe_terminal_output, wizard_process

pytestmark = [
    pytest.mark.installed,
    pytest.mark.skipif(
        os.environ.get("PAPILIO_RUN_INSTALLER_TESTS") != "1",
        reason="Opt in to creating a disposable full Compose installation.",
    ),
]
PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def installation_source(tmp_path: Path, image_mode: str) -> Iterator[PreparedRelease]:
    if image_mode == "prebuilt":
        with prebuilt_release(PROJECT, tmp_path) as prepared:
            yield prepared
    else:
        yield PreparedRelease(PROJECT)


@contextmanager
def telegram_api(compose: Compose, instance: str) -> Iterator[tuple[str, str]]:
    """External test double shares only the test I/O worker's loopback network."""
    worker = compose.run("ps", "-q", "worker-io", capture=True).stdout.decode().strip()
    assert worker, "The test-owned I/O worker container must exist."
    name = f"papilio-telegram-{instance}"
    program = "from telegram_server import TelegramServer; import signal; "
    program += "server=TelegramServer(); "
    program += "context=server.running(); address=context.__enter__(); "
    program += "print(address, flush=True); signal.pause()"
    subprocess.run(
        ["docker", "pull", "python:3.13-slim-bookworm"],
        check=True,
        capture_output=True,
        timeout=180,
    )
    process = subprocess.Popen(
        [
            "docker",
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            f"container:{worker}",
            "--mount",
            f"type=bind,src={PROJECT / 'panel/backend/tests'},dst=/testing,readonly",
            "--env",
            "PYTHONPATH=/testing",
            "python:3.13-slim-bookworm",
            "python",
            "-u",
            "-c",
            program,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert process.stdout is not None
        readable, _, _ = select.select([process.stdout], [], [], 30)
        assert readable, "The test Telegram double did not report readiness."
        address = process.stdout.readline().strip()
        assert address.startswith("http://127.0.0.1:")
        yield address, name
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, timeout=20, check=False
        )
        process.wait(timeout=20)
        if process.stdout is not None:
            process.stdout.close()


@pytest.mark.parametrize(
    ("environment", "scheme", "image_mode"),
    [
        ("test", "http", "auto"),
        ("production", "http", "auto"),
        ("sandbox", "https", "auto"),
        ("sandbox", "http", "prebuilt"),
    ],
)
def test_install_browser_backup_restore_and_restart_preserve_data(
    tmp_path: Path,
    environment: str,
    scheme: str,
    image_mode: str,
    installation_source: PreparedRelease,
) -> None:
    home = tmp_path / "installation"
    source = installation_source.source
    if installation_source.bundle is not None and installation_source.assets is not None:
        cache = home / "cache/images"
        cache.mkdir(parents=True)
        shutil.copy2(installation_source.assets / installation_source.bundle.asset, cache)
    instance = f"browser-{uuid4().hex[:10]}"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        tls_port = listener.getsockname()[1]
    identity_arguments = [
        "--home",
        str(home),
        "--environment",
        environment,
        "--instance",
        instance,
    ]
    command = [sys.executable, str(source / "deployment/papilio.py"), *identity_arguments]
    installation = None
    launcher = tmp_path / "commands/papilio"
    try:
        setup_arguments = [
            "--source",
            str(source),
            "--port",
            str(port),
            "--scheme",
            "https" if environment == "production" else scheme,
            "--https-port",
            str(tls_port),
            "--bind",
            "127.0.0.1",
            "--host",
            "papilio-http.test" if environment == "production" else "localhost",
            "--allow-unverified-host",
            "--command-path",
            str(launcher),
            "--image-mode",
            image_mode,
        ]
        if environment == "production":
            bootstrap = [
                "bash",
                str(PROJECT / "install.sh"),
                *identity_arguments,
                *setup_arguments,
                "--interactive",
            ]
            with wizard_process(tmp_path / "settings.json", command=bootstrap, pipe_input=True) as (
                terminal,
                process,
            ):
                read_until(terminal, b"PAPILIO")
                os.write(terminal, b"\t\t \x12")
                read_until(terminal, b"Review")
                os.write(terminal, b"\n")
                read_until(terminal, b"Installed command:", timeout=900)
                assert process.wait(timeout=10) == 0
        else:
            subprocess.run(
                [*command, "install", *setup_arguments],
                check=True,
                capture_output=True,
                timeout=900,
            )
        installation = Installation.load(home / environment / instance)
        compose = Compose(installation)
        rendered = json.loads(compose.run("config", "--format", "json", capture=True).stdout)
        assert len(rendered["services"]["gateway"]["ports"]) == (2 if scheme == "https" else 1)
        if scheme == "https":
            authority = compose.run(
                "exec",
                "-T",
                "gateway",
                "cat",
                "/data/caddy/pki/authorities/local/root.crt",
                capture=True,
            ).stdout.decode()
            context = ssl.create_default_context(cadata=authority)
            with urlopen(
                f"https://localhost:{tls_port}/health/live", context=context, timeout=10
            ) as response:
                assert response.status == 200
            with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
                connection.request(
                    "GET", "/login?next=%2Fbots", headers={"Host": f"localhost:{port}"}
                )
                response = connection.getresponse()
                assert response.status in {301, 308}
                assert (
                    response.headers["Location"]
                    == f"https://localhost:{tls_port}/login?next=%2Fbots"
                )
        token = (
            compose.run(
                "exec", "-T", "api", "python", "manage.py", "owner_setup_token", capture=True
            )
            .stdout.decode()
            .strip()
        )
        browser_host = "papilio-http.test" if environment == "production" else "127.0.0.1"
        if scheme == "https":
            browser_host = "localhost"
        browser_port = tls_port if scheme == "https" else port
        browser_environment = os.environ | {
            "PAPILIO_BROWSER_URL": f"{scheme}://{browser_host}:{browser_port}",
            "PAPILIO_BROWSER_INSECURE_DOMAIN": str(environment == "production").lower(),
            "PAPILIO_BROWSER_LOCAL_TLS": str(scheme == "https").lower(),
            "PAPILIO_SETUP_TOKEN": token,
            "PAPILIO_BROWSER_USERNAME": "browser-owner",
            "PAPILIO_BROWSER_PASSWORD": "isolated-browser-test-password-749!",
        }
        with telegram_api(compose, instance) as (api_address, api_container):
            browser_environment["PAPILIO_TEST_TELEGRAM_API_URL"] = api_address
            browser_environment["PAPILIO_TEST_TELEGRAM_CONTAINER"] = api_container
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
            "from papilio_panel.modules.bots.models import Bot; "
            "from papilio_panel.shared.credentials import credential_cipher; "
            "bot=Bot.objects.get(label='browser-bot-edited'); "
            "assert bot.pairing_ttl_seconds == 91 and bot.admin_chat_id == 456789; "
            "assert not bot.periodic_task.enabled and bot.periodic_task.interval.every == 11; "
            "opened=credential_cipher().decrypt(bytes(bot.token_ciphertext)); "
            "assert opened.startswith(b'123456789:'); "
            "print('independent-read-passed')",
            capture=True,
        )
        assert result.stdout.strip() == b"independent-read-passed"
        next_source = tmp_path / "next-release"
        for folder in ("deployment", "panel/backend", "panel/frontend"):
            shutil.copytree(
                source / folder,
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
        shutil.copy2(source / ".dockerignore", next_source / ".dockerignore")
        next_version = f"0.0.0-upgrade.{uuid4().hex}"
        (next_source / "VERSION").write_text(next_version + "\n")
        version_file = next_source / "panel/backend/src/papilio_panel/__init__.py"
        previous_version = (source / "VERSION").read_text().strip()
        version_file.write_text(version_file.read_text().replace(previous_version, next_version))
        if image_mode == "prebuilt":
            for name in ("backend.Dockerfile", "frontend.Dockerfile"):
                shutil.copy2(PROJECT / "deployment" / name, next_source / "deployment" / name)
        upgrade_arguments = [str(launcher), "update", "--source", str(next_source)]
        if image_mode == "prebuilt":
            upgrade_arguments.extend(["--image-mode", "build"])
        upgrade_result = subprocess.run(upgrade_arguments, capture_output=True, timeout=900)
        assert upgrade_result.returncode == 0, safe_terminal_output(upgrade_result.stderr)
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
            f"assert __version__ == {next_version!r}; "
            "assert User.objects.filter(username='browser-owner').exists(); "
            "from papilio_panel.modules.nodes.models import Node; "
            "assert Node.objects.get(name='browser-node').runtime.request_timeout_seconds == 7; "
            "from django_celery_beat.models import PeriodicTask; "
            "schedule=PeriodicTask.objects.get(name__endswith='.node-outbox'); "
            "assert not schedule.enabled and schedule.interval.every == 9; "
            "from papilio_panel.modules.bots.models import Bot; "
            "bot=Bot.objects.get(label='browser-bot-edited'); "
            "assert bot.pairing_ttl_seconds == 91 and bot.admin_chat_id == 456789; "
            "assert not bot.periodic_task.enabled and bot.periodic_task.interval.every == 11; "
            "print('synthetic-upgrade-passed')",
            capture=True,
        )
        assert upgraded_state.stdout.strip() == b"synthetic-upgrade-passed"
    finally:
        root = home / environment / instance
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
                    f"import shutil; shutil.rmtree('/owned/{environment}/{instance}/state')",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
