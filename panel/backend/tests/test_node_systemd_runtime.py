"""Opt-in actual node installation and reboot on an explicitly disposable VM."""

import base64
import os
import shlex
import subprocess
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from conftest import until
from django.http import FileResponse
from test_nodes import node_input, owner_client
from xray_client import HttpTunnelProbe, subscription_client

ROOT = Path(__file__).resolve().parents[3]
VM_ID = "papilio-native-systemd-vm01"
pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.runtime,
    pytest.mark.skipif(
        os.environ.get("PAPILIO_RUN_NODE_SYSTEMD") != "1",
        reason="Requires explicitly disposable systemd VM and private SSH target settings.",
    ),
]


@dataclass(frozen=True)
class SystemdTarget:
    ssh_port: int
    agent_port: int
    inbound_port: int
    key: Path

    def options(self) -> tuple[str, ...]:
        return (
            "-i",
            str(self.key),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=3",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={self.key.parent / 'known_hosts'}",
        )

    def run(self, *command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                "ssh",
                *self.options(),
                "-p",
                str(self.ssh_port),
                "ubuntu@127.0.0.1",
                shlex.join(command),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if check:
            assert result.returncode == 0, result.stdout + result.stderr
        return result

    def copy(self, source: Path, destination: str) -> None:
        subprocess.run(
            [
                "scp",
                *self.options(),
                "-P",
                str(self.ssh_port),
                str(source),
                f"ubuntu@127.0.0.1:{destination}",
            ],
            capture_output=True,
            check=True,
            timeout=60,
        )


@pytest.fixture
def systemd_target() -> SystemdTarget:
    target = SystemdTarget(
        int(os.environ["PAPILIO_SYSTEMD_TEST_SSH_PORT"]),
        int(os.environ["PAPILIO_SYSTEMD_TEST_AGENT_PORT"]),
        int(os.environ["PAPILIO_SYSTEMD_TEST_INBOUND_PORT"]),
        Path(os.environ["PAPILIO_SYSTEMD_TEST_KEY"]).resolve(),
    )
    assert all(
        1 <= value <= 65535 for value in (target.ssh_port, target.agent_port, target.inbound_port)
    )
    assert target.key.is_file()
    marker = target.run("cat", "/etc/papilio-test-vm-id")
    assert marker.stdout.strip() == VM_ID, "Refusing changes outside the disposable test VM."
    assert target.run("ps", "-p", "1", "-o", "comm=").stdout.strip() == "systemd"
    return target


@pytest.mark.timeout(180)
def test_native_systemd_install_restart_reboot_and_preserved_operator_files(
    runtime: None,
    systemd_target: SystemdTarget,
    tmp_path: Path,
) -> None:
    target = systemd_target
    bundle = Path(os.environ["PAPILIO_NODE_BUNDLE"])
    binary = os.environ["PAPILIO_XRAY_BINARY"]
    client = owner_client("systemd-node-owner")
    made = client.post(
        "/api/v1/nodes",
        node_input("Disposable systemd node")
        | {
            "endpoint_url": f"https://127.0.0.1:{target.agent_port}",
            "runtime": {
                "listen_address": "0.0.0.0:9443",
                "xray_api_address": "127.0.0.1:10085",
                "request_timeout_seconds": 3,
            },
        },
        format="json",
    )
    assert made.status_code == 202
    node, work = made.json()["node"], made.json()["operation"]
    root = f"/api/v1/nodes/{node['id']}"
    until(lambda: client.get(root + f"/operations/{work['id']}").json()["status"] == "succeeded")
    response = client.post(root + "/bootstrap")
    assert isinstance(response, FileResponse) and response.status_code == 200
    stream = response.streaming_content
    assert isinstance(stream, Iterator)
    bootstrap = tmp_path / "bootstrap.zip"
    bootstrap.write_bytes(b"".join(stream))
    bootstrap.chmod(0o600)
    source = tmp_path / "source.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        archive.add(ROOT / "VERSION", arcname="papilio/VERSION")
        for path in sorted((ROOT / "deployment").rglob("*.py")):
            if "tests" not in path.parts:
                archive.add(path, arcname=str(Path("papilio") / path.relative_to(ROOT)))
    target.copy(source, "source.tar.gz")
    target.copy(bundle, "node.tar.gz")
    target.copy(bootstrap, "bootstrap.zip")
    target.run("tar", "-xzf", "source.tar.gz")
    home = "/opt/papilio"
    instance = f"{home}/nodes/test/{node['id']}"
    unit = f"papilio-node-test-{node['id']}.service"
    command = (
        "sudo",
        "python3",
        "papilio/deployment/papilio.py",
        "--home",
        home,
        "--environment",
        "test",
        "node",
        "install",
        "--bootstrap",
        "/home/ubuntu/bootstrap.zip",
        "--bundle",
        "/home/ubuntu/node.tar.gz",
        "--inbound-tag",
        "systemd-vless",
        "--port",
        "8443",
    )
    try:
        target.run(*command)
        until(lambda: target.run("systemctl", "is-active", unit, check=False).returncode == 0)
        assert target.run("systemctl", "is-enabled", unit).stdout.strip() == "enabled"
        assert (
            target.run("systemctl", "show", unit, "-p", "DynamicUser", "--value").stdout.strip()
            == "yes"
        )
        check = client.post(
            root + "/operations",
            {
                "request_key": str(uuid4()),
                "kind": "check_connection",
            },
            format="json",
        )
        assert check.status_code == 202
        until(
            lambda: (
                client.get(root + f"/operations/{check.json()['id']}").json()["status"]
                == "succeeded"
            )
        )
        core = client.post(
            "/api/v1/cores/xray",
            {
                "request_key": str(uuid4()),
                "node_id": node["id"],
                "name": "Systemd Xray",
            },
            format="json",
        )
        assert core.status_code == 201
        inbound = client.post(
            f"/api/v1/cores/{core.json()['id']}/xray/inbounds",
            {
                "request_key": str(uuid4()),
                "tag": "systemd-vless",
                "public_host": "127.0.0.1",
                "port": target.inbound_port,
            },
            format="json",
        )
        assert inbound.status_code == 201
        service = client.post(
            "/api/v1/services",
            {
                "request_key": str(uuid4()),
                "name": "Systemd persistent client",
                "core_id": core.json()["id"],
                "inbound_id": inbound.json()["id"],
            },
            format="json",
        )
        assert service.status_code == 202
        service_root = f"/api/v1/services/{service.json()['id']}"
        until(lambda: client.get(service_root).json()["status"] == "succeeded")
        link = client.get(service_root + "/subscription").json()["url"]
        uri = base64.b64decode(client.get(link).content).decode().strip()
        changed = client.put(
            service_root + "/synchronization",
            {
                "enabled": True,
                "interval_seconds": 1,
                "expected_revision": "1",
            },
            format="json",
        )
        assert changed.status_code == 200
        configuration = instance + "/credentials/agent.json"
        target.run(
            "sudo",
            "python3",
            "-c",
            "import json,pathlib; p=pathlib.Path(" + repr(configuration) + "); "
            "v=json.loads(p.read_text()); v['idle_timeout_seconds']=67; "
            "p.write_text(json.dumps(v))",
        )
        digest = target.run(
            "sudo", "sha256sum", configuration, instance + "/credentials/server.key"
        ).stdout
        target.run(*command)
        assert (
            target.run(
                "sudo", "sha256sum", configuration, instance + "/credentials/server.key"
            ).stdout
            == digest
        )
        with subscription_client(binary, tmp_path, uri, origin_host="10.0.2.2") as probe:
            assert probe.fetch() == b"papilio-actual-subscription-client"
            old_pid = target.run(
                "systemctl", "show", unit, "-p", "MainPID", "--value"
            ).stdout.strip()
            target.run("sudo", "systemctl", "kill", "--signal=KILL", "--kill-whom=main", unit)
            until(
                lambda: (
                    target.run("systemctl", "show", unit, "-p", "MainPID", "--value").stdout.strip()
                    not in {"0", old_pid}
                )
            )
            until(lambda: tunnel_ready(probe))
            boot = target.run("cat", "/proc/sys/kernel/random/boot_id").stdout.strip()
            target.run("sudo", "systemctl", "reboot", check=False)
            until(lambda: boot_recovered(target, boot, unit), timeout=60)
            until(lambda: tunnel_ready(probe))
            assert (
                target.run(
                    "sudo", "sha256sum", configuration, instance + "/credentials/server.key"
                ).stdout
                == digest
            )
            target.run("sudo", "systemctl", "stop", unit)
            with pytest.raises(OSError):
                probe.fetch()
            assert target.run("sudo", "test", "-f", configuration).returncode == 0
            target.run("sudo", "systemctl", "start", unit)
            until(lambda: tunnel_ready(probe))
        assert client.get(service_root + "/subscription").json()["url"] == link
        assert client.get(service_root).json()["attempts"] == 1
    finally:
        target.run("sudo", "systemctl", "disable", "--now", unit, check=False)
        target.run("sudo", "rm", "-f", f"/etc/systemd/system/{unit}")
        target.run("sudo", "systemctl", "daemon-reload")
        target.run("sudo", "rm", "-rf", instance)


def tunnel_ready(probe: HttpTunnelProbe) -> bool:
    try:
        return probe.fetch() == b"papilio-actual-subscription-client"
    except OSError:
        return False


def boot_recovered(target: SystemdTarget, previous_boot: str, unit: str) -> bool:
    result = target.run("cat", "/proc/sys/kernel/random/boot_id", check=False)
    return (
        result.returncode == 0
        and result.stdout.strip() not in {"", previous_boot}
        and target.run("systemctl", "is-active", unit, check=False).returncode == 0
    )
