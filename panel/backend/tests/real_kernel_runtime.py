"""Real tunnel traffic inside two isolated, internal-only Docker namespaces."""

import configparser
import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from tests.real_core_runtime import (
    RealCoreRuntime,
    TrafficTarget,
    TrafficTargetServer,
)


class KernelCoreRuntime:
    def __init__(self, root: Path, image: str, timeout: float):
        self.root, self.image, self.timeout = root, image, timeout
        self.resources = ExitStack()
        self.prefix = "papilio-core-test-" + uuid4().hex[:12]
        self.network = self.prefix + "-network"
        self.server, self.client = (
            self.prefix + "-server",
            self.prefix + "-client",
        )

    @staticmethod
    def docker(*args, timeout: float = 30):
        result = subprocess.run(
            ["docker", *args], capture_output=True, timeout=timeout
        )
        if result.returncode:
            raise RuntimeError(result.stderr.decode())
        return result.stdout.decode().strip()

    def __enter__(self):
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.resources.__enter__()
        try:
            self.docker("network", "create", "--internal", self.network)
            self.resources.callback(self.docker, "network", "rm", self.network)
            tests = Path(__file__).resolve().parent
            for name in (self.server, self.client):
                self.docker(
                    "run",
                    "-d",
                    "--name",
                    name,
                    "--network",
                    self.network,
                    "--cap-add",
                    "NET_ADMIN",
                    "--device",
                    "/dev/net/tun",
                    "--read-only",
                    "--tmpfs",
                    "/tmp",
                    "--mount",
                    "type=bind,src=/usr,dst=/usr,readonly",
                    "--mount",
                    "type=bind,src=/usr/lib,dst=/lib,readonly",
                    "--mount",
                    "type=bind,src=/usr/lib64,dst=/lib64,readonly",
                    "--mount",
                    f"type=bind,src={tests},dst=/acceptance/tests,readonly",
                    "--mount",
                    f"type=bind,src={self.root},dst=/fixtures",
                    "--entrypoint",
                    "/usr/bin/sleep",
                    self.image,
                    "infinity",
                )
                self.resources.callback(self.docker, "rm", "-f", name)
            facts = json.loads(self.docker("inspect", self.server))[0]
            self.server_ip = facts["NetworkSettings"]["Networks"][
                self.network
            ]["IPAddress"]
            return self
        except BaseException:
            self.resources.close()
            raise

    def __exit__(self, *args):
        self.resources.__exit__(*args)
        remaining = self.docker(
            "ps",
            "-a",
            "--filter",
            f"name={self.prefix}",
            "--format",
            "{{.Names}}",
        )
        assert not remaining

    def file(self, name, content):
        target = self.root / name
        target.write_text(content)
        target.chmod(0o600)

    def traffic(self, server, client, protocol, client_identity=None):
        self.file("server.conf", server)
        self.file("client.conf", client)
        self.file("server.log", "")
        self.file("client.log", "")
        self.file(
            "case.json",
            json.dumps(
                {
                    "protocol": protocol,
                    "client_identity": client_identity,
                    "timeout": self.timeout,
                }
            ),
        )
        self.docker(
            "exec",
            "-d",
            "--workdir",
            "/acceptance",
            self.server,
            "/usr/bin/python3",
            "-m",
            "tests.real_kernel_runtime",
            "server",
        )
        try:
            output = self.docker(
                "exec",
                "--workdir",
                "/acceptance",
                self.client,
                "/usr/bin/python3",
                "-m",
                "tests.real_kernel_runtime",
                "client",
                timeout=self.timeout + 15,
            )
            assert output == "traffic verified", output
        finally:
            # Removing owned namespaces terminates all their descendants.
            self.resources.close()


def configure_wireguard(path, name):
    parsed = configparser.ConfigParser(strict=False)
    parsed.read(path)
    address = parsed["Interface"]["Address"]
    subprocess.run(
        ["ip", "link", "add", name, "type", "wireguard"], check=True
    )
    stripped = subprocess.run(
        ["wg-quick", "strip", str(path)], check=True, capture_output=True
    ).stdout
    temporary = Path("/tmp/stripped.conf")
    temporary.write_bytes(stripped)
    temporary.chmod(0o600)
    subprocess.run(["wg", "setconf", name, str(temporary)], check=True)
    subprocess.run(["ip", "address", "add", address, "dev", name], check=True)
    subprocess.run(["ip", "link", "set", name, "up"], check=True)


def admit_openvpn(listener, expected_identity):
    connection, _ = listener.accept()
    with connection, connection.makefile("r") as incoming:
        cid, kid, identity = None, None, None
        for line in incoming:
            if line.startswith(">HOLD:"):
                connection.sendall(b"hold release\n")
            elif line.startswith(">CLIENT:CONNECT,") or line.startswith(
                ">CLIENT:REAUTH,"
            ):
                _, cid, kid = line.strip().split(",")
                identity = None
            elif line.startswith(">CLIENT:ENV,common_name="):
                identity = line.strip().split("=", 1)[1]
            elif line.startswith(">CLIENT:ENV,END") and cid is not None:
                command = (
                    f"client-auth-nt {cid} {kid}\n"
                    if identity == expected_identity
                    else f"client-deny {cid} {kid} denied\n"
                )
                connection.sendall(command.encode())
                cid, kid = None, None


def namespace_main(role):
    root = Path("/fixtures")
    case = json.loads((root / "case.json").read_text())
    timeout = case["timeout"]
    protocol = case["protocol"]
    with ExitStack() as resources:
        if protocol == "wireguard":
            configure_wireguard(root / f"{role}.conf", "papilio-test")
            if role == "client":
                subprocess.run(
                    [
                        "ip",
                        "route",
                        "add",
                        "10.44.0.1/32",
                        "dev",
                        "papilio-test",
                    ],
                    check=True,
                )
        else:
            core_args = ["openvpn", "--config", str(root / f"{role}.conf")]
            if role == "server":
                if "dev tap\n" in (root / "server.conf").read_text():
                    subprocess.run(
                        [
                            "ip",
                            "link",
                            "add",
                            "papilio-bridge",
                            "type",
                            "bridge",
                        ],
                        check=True,
                    )
                    subprocess.run(
                        [
                            "ip",
                            "addr",
                            "add",
                            "10.43.0.1/24",
                            "dev",
                            "papilio-bridge",
                        ],
                        check=True,
                    )
                    subprocess.run(
                        ["ip", "link", "set", "papilio-bridge", "up"],
                        check=True,
                    )
                    subprocess.run(
                        [
                            "ip",
                            "tuntap",
                            "add",
                            "dev",
                            "papilio-tap",
                            "mode",
                            "tap",
                        ],
                        check=True,
                    )
                    subprocess.run(
                        [
                            "ip",
                            "link",
                            "set",
                            "papilio-tap",
                            "master",
                            "papilio-bridge",
                        ],
                        check=True,
                    )
                    subprocess.run(
                        ["ip", "link", "set", "papilio-tap", "up"],
                        check=True,
                    )
                    core_args.extend(
                        ["--dev", "papilio-tap", "--dev-type", "tap"]
                    )
                listener = socket.socket(socket.AF_UNIX)
                listener.bind("/tmp/papilio-test.sock")
                listener.listen(1)
                resources.callback(listener.close)
                threading.Thread(
                    target=admit_openvpn,
                    args=(listener, case["client_identity"]),
                    daemon=True,
                ).start()
            log = resources.enter_context((root / f"{role}.log").open("ab"))
            process = subprocess.Popen(
                core_args,
                stdout=log,
                stderr=log,
            )
            resources.callback(RealCoreRuntime.stop, process)
        if role == "server":
            target = TrafficTargetServer(("0.0.0.0", 45321))
            resources.callback(target.server_close)
            target.serve_forever()
        else:
            import urllib.request

            address = "10.44.0.1" if protocol == "wireguard" else "10.43.0.1"
            deadline = time.monotonic() + timeout
            verified = False
            while time.monotonic() < deadline:
                try:
                    request = urllib.request.urlopen(
                        f"http://{address}:45321/proof", timeout=1
                    )
                    verified = request.read() == TrafficTarget.payload
                except OSError:
                    pass
                if verified:
                    break
                time.sleep(0.1)
            assert verified, (
                "No real tunnel traffic; inspect private core logs"
            )
            print("traffic verified")


if __name__ == "__main__":
    os.chdir("/acceptance")
    namespace_main(sys.argv[1])
