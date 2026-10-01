"""Read-only VPS capacity snapshot; thresholds are advisory, not a capacity proof."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

SOCKET = "/opt/papilio-proxy/data/node/node.sock"


def cpu() -> tuple[int, int, int]:
    n = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
    return sum(n), n[3] + n[4], n[7]


def network(interface: str) -> tuple[int, int]:
    for line in Path("/proc/net/dev").read_text().splitlines()[2:]:
        name, values = line.split(":", 1)
        if name.strip() == interface:
            parts = values.split()
            return int(parts[0]), int(parts[8])
    raise RuntimeError(f"Network interface {interface!r} not found")


def memory() -> tuple[int, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        if name in {"MemTotal", "MemAvailable"}:
            values[name] = int(value.split()[0])
    return values["MemTotal"], values["MemAvailable"]


def node() -> tuple[int, float | None]:
    result = subprocess.run(
        ["curl", "-fsS", "--max-time", "3", "--unix-socket", SOCKET,
         "http://localhost/v1/usage"],
        capture_output=True, check=False, timeout=5,
    )
    if result.returncode:
        raise RuntimeError("Private node usage endpoint is unavailable")
    active = [item for item in json.loads(result.stdout) if not item["revoked"]]
    if not active:
        return 0, None
    age = max(
        (datetime.now(UTC) - datetime.fromisoformat(item["measured_at"])).total_seconds()
        for item in active
    )
    return len(active), round(age, 1)


def connections(port: int) -> int:
    result = subprocess.run(
        ["ss", "-Htan", "state", "established", "(", "sport", "=", f":{port}", ")"],
        capture_output=True, check=False, timeout=5,
    )
    if result.returncode:
        raise RuntimeError("Could not read TCP connection state")
    return len(result.stdout.splitlines())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--interface", default="eth0")
    parser.add_argument("--cpu-warn", type=float, default=70)
    parser.add_argument("--memory-warn", type=float, default=25)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30:
        parser.error("--seconds must be between 1 and 30")
    if not 0 < args.cpu_warn < 100 or not 0 < args.memory_warn < 100:
        parser.error("Threshold percentages must be between 0 and 100")

    c1, i1, s1 = cpu()
    rx1, tx1 = network(args.interface)
    start = time.monotonic()
    time.sleep(args.seconds)
    elapsed = time.monotonic() - start
    c2, i2, s2 = cpu()
    rx2, tx2 = network(args.interface)
    total, available = memory()
    active, counter_age = node()
    ticks = max(1, c2 - c1)
    cpu_pct = round(100 * (ticks - (i2 - i1)) / ticks, 1)
    steal_pct = round(100 * (s2 - s1) / ticks, 1)
    available_pct = round(100 * available / total, 1)
    warnings = []
    if cpu_pct >= args.cpu_warn:
        warnings.append("CPU pressure: repeat at peak hour before upgrading")
    if steal_pct >= 5:
        warnings.append("High CPU steal: investigate VPS host contention")
    if available_pct <= args.memory_warn:
        warnings.append("Low available RAM: inspect containers and consider upgrade")
    if counter_age is not None and counter_age > 10:
        warnings.append("Stale counters: quota enforcement needs attention")

    print(json.dumps({
        "sample_seconds": round(elapsed, 1),
        "cpu_percent": cpu_pct, "cpu_steal_percent": steal_pct,
        "memory_available_mib": available // 1024,
        "memory_available_percent": available_pct,
        "network_rx_mbps": round((rx2 - rx1) * 8 / elapsed / 1_000_000, 2),
        "network_tx_mbps": round((tx2 - tx1) * 8 / elapsed / 1_000_000, 2),
        "vless_connections": connections(8443),
        "vmess_connections": connections(8444),
        "active_accounts": active,
        "oldest_counter_age_seconds": counter_age,
        "warnings": warnings,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
