"""Actual unprivileged node image startup and cancellation before bootstrap."""

import io
import os
import subprocess
import tarfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from deployment.papilio_installer.images import ImageRole, docker_platform, image_reference

PROJECT = Path(__file__).resolve().parents[2]
STATE = "/var/lib/papilio/local-node"
pytestmark = [
    pytest.mark.installed,
    pytest.mark.skipif(
        os.environ.get("PAPILIO_RUN_INSTALLER_TESTS") != "1",
        reason="Opt in to creating isolated native Docker resources.",
    ),
]


def docker(*arguments: str, data: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", *arguments],
        input=data,
        capture_output=True,
        check=False,
        timeout=600,
    )


def eventually(predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    pytest.fail("The native container completion condition was not reached.")


@pytest.fixture(scope="module")
def node_image() -> Iterator[str]:
    supplied = os.environ.get("PAPILIO_TEST_RELEASE_IMAGES")
    image = (
        image_reference(
            ImageRole.NODE, (PROJECT / "VERSION").read_text().strip(), docker_platform()
        )
        if supplied
        else f"papilio-test-node:{uuid4().hex}"
    )
    if not supplied:
        result = docker(
            "build",
            "--tag",
            image,
            "--file",
            str(PROJECT / "deployment/node.Dockerfile"),
            str(PROJECT),
        )
        assert result.returncode == 0, result.stderr.decode()
    try:
        yield image
    finally:
        if not supplied:
            assert docker("image", "rm", "--force", image).returncode == 0


@pytest.fixture
def node_volume() -> Iterator[str]:
    name = f"papilio-test-node-{uuid4().hex}"
    assert docker("volume", "create", name).returncode == 0
    try:
        yield name
    finally:
        assert docker("volume", "rm", name).returncode == 0


def test_node_image_waits_without_root_and_cancels_without_bootstrap_files(
    node_image: str,
    node_volume: str,
) -> None:
    name = f"papilio-test-node-{uuid4().hex}"
    result = docker(
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--mount",
        f"type=volume,src={node_volume},dst={STATE},readonly",
        node_image,
    )
    assert result.returncode == 0, result.stderr.decode()
    try:
        eventually(
            lambda: b"Papilio node agent awaiting configuration" in docker("logs", name).stdout
        )
        identity = docker(
            "inspect", "--format", "{{.Config.User}} {{.State.Running}} {{.Path}}", name
        )
        assert identity.stdout.decode().strip() == "10001:10001 true /usr/local/bin/papilio-agent"
        assert docker("stop", "--time", "5", name).returncode == 0
        assert docker("inspect", "--format", "{{.State.ExitCode}}", name).stdout.strip() == b"0"
        files = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "find",
            "--mount",
            f"type=volume,src={node_volume},dst={STATE},readonly",
            node_image,
            STATE,
            "-mindepth",
            "1",
        )
        assert files.returncode == 0 and files.stdout == b""
        core = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "/usr/local/bin/xray",
            node_image,
            "version",
        )
        assert core.returncode == 0 and b"26.3.27" in core.stdout
        notices = docker(
            "run",
            "--rm",
            "--network",
            "none",
            "--entrypoint",
            "find",
            node_image,
            "/usr/share/doc/papilio-node",
            "-type",
            "f",
        )
        assert notices.returncode == 0
        assert all(
            name in notices.stdout
            for name in (b"Papilio-MIT.txt", b"Xray-MPL-2.0.txt", b"Go-dependencies.txt")
        )
    finally:
        assert docker("rm", "--force", name).returncode == 0


def test_node_image_rejects_invalid_published_config_without_echoing_it(
    node_image: str,
    node_volume: str,
) -> None:
    output = io.BytesIO()
    sentinel = b"private-config-content-must-not-escape"
    with tarfile.open(fileobj=output, mode="w") as archive:
        item = tarfile.TarInfo("instance/agent.json")
        item.mode, item.size = 0o600, len(sentinel)
        archive.addfile(item, io.BytesIO(sentinel))
    copied = docker(
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--entrypoint",
        "tar",
        "--mount",
        f"type=volume,src={node_volume},dst={STATE}",
        node_image,
        "-xf",
        "-",
        "-C",
        STATE,
        data=output.getvalue(),
    )
    assert copied.returncode == 0, copied.stderr.decode()
    result = docker(
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--mount",
        f"type=volume,src={node_volume},dst={STATE},readonly",
        node_image,
    )
    assert result.returncode == 1
    assert b"invalid or unreadable node configuration" in result.stderr
    assert sentinel not in result.stdout + result.stderr
