"""Run a bounded, localhost-only 100-user control-plane test on the VPS.

This does not measure Internet throughput or prove 100 simultaneous customers.
The temporary Xray container and all test credentials are removed on exit.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path("/opt/papilio-proxy/data/xray")
IMAGE = (
    "ghcr.io/xtls/xray-core@sha256:"
    "592ec4d11f656db95598d01e76dbcc6e002d67360b96a5436500a938230f52c7"
)
NAME = "papilio-capacity-smoke"


def run(*args: str, timeout: int = 15) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, capture_output=True, check=False, timeout=timeout)


def request(sock: Path, method: str, path: str, body: dict[str, object] | None = None) -> object:
    args = ["curl", "-fsS", "--max-time", "15", "--unix-socket", str(sock), "-X", method]
    if body is not None:
        args += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
    args += ["http://localhost" + path]
    result = subprocess.run(
        args, input=json.dumps(body).encode() if body is not None else None,
        capture_output=True, check=False, timeout=18,
    )
    if result.returncode:
        raise RuntimeError(f"Isolated node {method} {path} failed: curl {result.returncode}")
    return json.loads(result.stdout) if result.stdout else None


def free(port: int) -> bool:
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


def p95(values: list[float]) -> float:
    return sorted(values)[int((len(values) - 1) * 0.95)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.users <= 100:
        parser.error("--users must be between 1 and 100")
    if os.geteuid() != 0 or not (ROOT / "config.json").is_file():
        parser.error("Run as root on the deployed VPS")
    if any(not free(port) for port in (18443, 18444, 10086)):
        parser.error("An isolated test port is already in use")
    if run("docker", "inspect", NAME).returncode == 0:
        parser.error("The isolated test container already exists")

    config = json.loads((ROOT / "config.json").read_text())
    ports = {"vless-reality-in": 18443, "vmess-ws-tls-in": 18444, "api-in": 10086}
    for inbound in config["inbounds"]:
        inbound["listen"] = "127.0.0.1"
        inbound["port"] = ports[inbound["tag"]]
        if inbound["tag"] != "api-in" and inbound["settings"]["clients"]:
            parser.error("Refusing a nonempty persistent Xray configuration")

    with tempfile.TemporaryDirectory(prefix="papilio-capacity-") as directory:
        work = Path(directory)
        os.chown(work, 65532, 10001)
        work.chmod(0o770)
        config_path = work / "config.json"
        config_path.write_text(json.dumps(config))
        os.chown(config_path, 65532, 10001)
        config_path.chmod(0o400)
        sock = work / "test.sock"
        start = run(
            "docker", "run", "-d", "--rm", "--name", NAME, "--network", "host",
            "--user", "65532:10001", "--read-only", "--memory", "256m",
            "--pids-limit", "128", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "-e", "PAPILIO_XRAY_CONFIG=/etc/xray/config.json",
            "-e", "PAPILIO_NODE_SOCKET=/run/papilio/test.sock",
            "-v", f"{config_path}:/etc/xray/config.json:ro",
            "-v", f"{ROOT / 'papilio-proxy'}:/usr/local/bin/papilio-proxy:ro",
            "-v", f"{ROOT / 'certs'}:/etc/xray/certs:ro",
            "-v", f"{work}:/run/papilio",
            "--entrypoint", "/usr/local/bin/papilio-proxy", IMAGE, "serve",
            timeout=30,
        )
        if start.returncode:
            raise RuntimeError("Isolated Xray container did not start")
        try:
            for _ in range(100):
                if sock.exists() and run(
                    "curl", "-fsS", "--max-time", "1", "--unix-socket", str(sock),
                    "-X", "POST", "http://localhost/v1/heartbeat", timeout=2,
                ).returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Isolated node did not become ready")

            latencies: list[float] = []
            started_at = time.perf_counter()
            for _ in range(args.users):
                payload = {
                    "id": str(uuid4()), "email": "capacity-" + uuid4().hex,
                    "label": "Capacity test", "quota_bytes": 10_000_000,
                    "duration_days": 1,
                }
                before = time.perf_counter()
                response = request(sock, "POST", "/v1/ensure", payload)
                if not isinstance(response, dict) or response["snapshot"]["revoked"]:
                    raise RuntimeError("Isolated provision did not return an active user")
                latencies.append(time.perf_counter() - before)
            provision_seconds = time.perf_counter() - started_at
            time.sleep(2)
            reads: list[float] = []
            for _ in range(10):
                before = time.perf_counter()
                usage = request(sock, "GET", "/v1/usage")
                reads.append(time.perf_counter() - before)
                if not isinstance(usage, list) or len(usage) != args.users:
                    raise RuntimeError("Isolated node lost an entitlement")
                time.sleep(0.1)
            stats = run(
                "docker", "stats", "--no-stream", "--format",
                "{{.CPUPerc}} {{.MemUsage}}", NAME, timeout=10,
            )
            print(json.dumps({
                "users": args.users,
                "provision_total_seconds": round(provision_seconds, 3),
                "provision_p50_ms": round(statistics.median(latencies) * 1000, 1),
                "provision_p95_ms": round(p95(latencies) * 1000, 1),
                "usage_p95_ms": round(p95(reads) * 1000, 1),
                "container_cpu_memory": stats.stdout.decode().strip(),
            }))
        finally:
            if run("docker", "rm", "-f", NAME, timeout=20).returncode:
                raise RuntimeError("CRITICAL: isolated container cleanup failed")


if __name__ == "__main__":
    main()
