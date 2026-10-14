"""Owned real Go/Xray/native API acceptance; no HTTP or counter doubles."""

import ipaddress
import json
import os
import select
import signal
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import httpx

from tests.core_provisioning_agent import _data, _stop_core
from tests.resource_reports import (
    ProcessResourceSample,
    ResourceMetrics,
    ResourceReportPolicy,
    sample_resource_report,
)
from tests.scheduler_runtime import exercise_native_installed_purchase


def _stats(binary, port, identity, timeout_seconds=1):
    result = subprocess.run(
        [
            str(binary),
            "api",
            "statsquery",
            f"-server=127.0.0.1:{port}",
            f"-timeout={timeout_seconds}",
            f"-pattern=user>>>{identity}>>>traffic>>>",
        ],
        capture_output=True,
        timeout=timeout_seconds + 2,
    )
    return result


def _exact(sock, size):
    value = b""
    while len(value) < size:
        chunk = sock.recv(size - len(value))
        if not chunk:
            raise OSError("Owned proxy closed")
        value += chunk
    return value


def _socks(socks_port, host, port):
    sock = socket.create_connection(("127.0.0.1", socks_port), timeout=2)
    try:
        sock.sendall(b"\x05\x01\x00")
        if _exact(sock, 2) != b"\x05\x00":
            raise OSError("Owned SOCKS negotiation failed")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            name = host.encode("ascii")
            destination = b"\x03" + bytes([len(name)]) + name
        else:
            destination = (
                bytes([1 if address.version == 4 else 4]) + address.packed
            )
        sock.sendall(b"\x05\x01\x00" + destination + struct.pack("!H", port))
        reply = _exact(sock, 4)
        if reply[1] != 0:
            raise OSError("Owned SOCKS destination denied")
        size = {1: 4, 4: 16}.get(reply[3])
        if reply[3] == 3:
            size = _exact(sock, 1)[0]
        if size is None:
            raise OSError("Owned SOCKS response invalid")
        _exact(sock, size + 2)
        return sock
    except BaseException:
        sock.close()
        raise


def _subscriber_rpc(
    runtime, outbound, host, port, identity, name, accepted=False
):
    """Real gRPC over an owned TCP-to-SOCKS tunnel, no fake Stats responses."""
    socks_port = runtime.port()
    path = runtime.file(
        name + "-client.json",
        json.dumps(
            {
                "inbounds": [
                    {
                        "type": "socks",
                        "listen": "127.0.0.1",
                        "listen_port": socks_port,
                    }
                ],
                "outbounds": [{**outbound, "tag": "proxy"}],
                "route": {"final": "proxy"},
            }
        ),
    )
    client = runtime.start(
        name + "-client",
        [str(runtime.binaries / "sing-box"), "run", "-c", str(path)],
    )

    def ready():
        try:
            with socket.create_connection(
                ("127.0.0.1", socks_port), timeout=0.2
            ):
                return True
        except OSError:
            return False

    _wait(ready, bool, "Owned subscriber client never became ready", seconds=3)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3)
    finished = threading.Event()
    phase = {"phase": "accept", "upstream_bytes": 0, "downstream_bytes": 0}

    def tunnel():
        try:
            with listener.accept()[0] as incoming:
                phase["phase"] = "socks_connect"
                deadline = time.monotonic() + 2
                upstream = None
                while time.monotonic() < deadline:
                    try:
                        upstream = _socks(socks_port, host, port)
                        break
                    except OSError:
                        time.sleep(0.05)
                if upstream is None:
                    return
                phase["phase"] = "relay"
                with upstream:
                    pair = (incoming, upstream)
                    while not finished.is_set():
                        ready, _, _ = select.select(pair, [], [], 0.1)
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                phase["phase"] = "relay_eof"
                                return
                            phase[
                                "upstream_bytes"
                                if source is incoming
                                else "downstream_bytes"
                            ] += len(data)
                            (
                                upstream if source is incoming else incoming
                            ).sendall(data)
        except OSError as error:
            phase["phase"] = type(error).__name__

    thread = threading.Thread(target=tunnel, daemon=True)
    thread.start()
    try:
        result = _stats(
            runtime.binaries / "xray",
            listener.getsockname()[1],
            identity,
            timeout_seconds=4 if accepted else 1,
        )
        error_text = result.stderr.decode("utf8", errors="replace").lower()
        error_code = (
            "deadline"
            if "deadline" in error_text
            else "eof"
            if "eof" in error_text
            else "rpc_failed"
        )
        assert (result.returncode == 0) is accepted, (
            f"Subscriber RPC boundary failed: exit={result.returncode} "
            f"error={error_code} phase={phase}"
        )
        if accepted:
            assert isinstance(json.loads(result.stdout), dict), (
                "Management RPC was not parsed"
            )
    finally:
        finished.set()
        listener.close()
        thread.join(timeout=4)
        assert not thread.is_alive(), "Owned SOCKS tunnel did not finish"
        runtime.stop(client)


def _journal(directory, core_id):
    return json.loads(
        (directory / "usage-journal" / str(core_id) / "state.json").read_text()
    )


def _wait(call, complete, message, seconds: float = 20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = call()
        if complete(value):
            return value
        time.sleep(0.1)
    raise AssertionError(message)


def _sample_owned(process: subprocess.Popen[bytes]) -> ProcessResourceSample:
    """Point-in-time RSS of Go plus currently observable descendants only."""
    pending, seen, rss = [process.pid], set(), 0
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        try:
            status = Path(f"/proc/{pid}/status").read_text()
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    rss += int(line.split()[1])
            children = Path(f"/proc/{pid}/task/{pid}/children").read_text()
            pending.extend(int(item) for item in children.split())
        except (FileNotFoundError, ProcessLookupError):
            pass
    return {"observed_processes": len(seen), "rss_kib": rss}


def _profile(api, request_id):
    tasks = _data(
        api.get(f"/v1/admin/provisioning/{request_id}/tasks"),
        "Native tasks read failed",
    )
    assert len(tasks) == 1 and tasks[0]["state"] == "applied", (
        "Native purchased profile not applied"
    )
    return tasks[0]


def _uri(api, profile_id):
    return _data(
        api.post(
            f"/v1/admin/network/configurations/profiles/{profile_id}/client-download"
        ),
        "Native client download failed",
    )["content"].strip()


def _usage_rows(api, subscription_id):
    return _data(
        api.get(
            "/v1/admin/usage/grants",
            params={"subscription_id": subscription_id, "per_page": 16},
        ),
        "Native grant read failed",
    )


def _replay_real_report(api, node_api, directory, core, subscription):
    state = _journal(directory, core["id"])
    epoch = state["usage_epochs"][-1]
    profile = epoch["profiles"][0]
    assert profile["sequence"] > 0 and profile["sampled_at"], (
        "No durable actual counter sample"
    )
    report = {
        "event_id": (
            f"usage_{epoch['id']}_"
            f"{profile['binding']['profile_id']}_{profile['sequence']}"
        ),
        "sequence": profile["sequence"],
        "upload_bytes": profile["upload_bytes"],
        "download_bytes": profile["download_bytes"],
        "sampled_at": profile["sampled_at"],
        "final": False,
        "process_epoch": epoch["id"],
    }
    before = _data(
        api.get(f"/v1/admin/subscriptions/{subscription['id']}"),
        "Native usage read failed",
    )["used_bytes"]
    path = (
        f"/v1/nodes/{node_api.headers['X-Papilio-Node-Code']}"
        f"/usage/grants/{profile['grant']['id']}/reports"
    )
    first = _data(
        node_api.post(path, json=report), "Actual usage replay failed"
    )
    second = _data(
        node_api.post(path, json=report),
        "Duplicate actual usage replay failed",
    )
    assert first["id"] == second["id"], (
        "Real usage event replay duplicated ledger"
    )
    after = _data(
        api.get(f"/v1/admin/subscriptions/{subscription['id']}"),
        "Native usage replay read failed",
    )["used_bytes"]
    assert before == after, "Actual counter replay charged twice"


def _unmapped_refusal(api, runtime, node, kind):
    core = _data(
        api.post(
            f"/v1/admin/network/nodes/{node['node']['id']}/cores",
            json={
                "code": "usage_unmapped_" + kind,
                "label": "Owned unmapped rejection",
                "kind": kind,
            },
        ),
        "Unmapped core create failed",
    )
    port = runtime.port()
    _data(
        api.post(
            "/v1/admin/network/configurations",
            json={
                "node_id": node["node"]["id"],
                "core_id": core["id"],
                "listen_port": port,
                "label": "Owned unmapped inbound",
                "options": {
                    "protocol": "vless_reality",
                    "listen_address": "127.0.0.1",
                    "server_name": "localhost",
                    "target_port": runtime.handshake_port,
                },
            },
        ),
        "Unmapped configuration create failed",
    )
    state = _data(
        api.get(f"/v1/admin/network/cores/{core['id']}/runtime"),
        "Unmapped state read failed",
    )
    refused = api.post(
        f"/v1/admin/network/cores/{core['id']}/runtime/revisions",
        json={"expected_revision": state["revision"], "mode": "merged"},
    )
    assert refused.status_code == 409, "Unmapped Stats-node bundle not refused"
    assert (
        refused.json()["error"]["message_code"]
        == "runtime_usage_isolation_required"
    ), "Unmapped rejection reason changed"
    with socket.socket() as sock:
        sock.settimeout(0.5)
        assert sock.connect_ex(("127.0.0.1", port)) != 0, (
            "Refused core acquired listener"
        )


def _redirect_refusal(api, runtime, directory, core, stats_port, identity):
    before = _journal(directory, core["id"])
    configuration = _data(
        api.get(
            "/v1/admin/network/configurations", params={"core_id": core["id"]}
        ),
        "Owned configuration read failed",
    )[0]
    _data(
        api.put(
            f"/v1/admin/network/configurations/{configuration['id']}/server-json",
            json={
                "expected_revision": configuration["revision"],
                "reason": "Owned Stats redirect safety acceptance",
                "document": {
                    "mode": "managed",
                    "source": json.dumps(
                        {
                            "inbounds": [{"$papilio": "managed"}],
                            "outbounds": [
                                {
                                    "tag": "direct",
                                    "protocol": "freedom",
                                    "settings": {
                                        "redirect": f"127.0.0.1:{stats_port}"
                                    },
                                }
                            ],
                        }
                    ),
                },
            },
        ),
        "Offline unsafe JSON edit failed",
    )
    base = f"/v1/admin/network/cores/{core['id']}/runtime"
    state = _data(api.get(base), "Unsafe candidate runtime read failed")
    result = api.post(
        base + "/revisions",
        json={"expected_revision": state["revision"], "mode": "merged"},
    )
    assert result.status_code == 409, (
        "Unsafe redirect installed candidate accepted"
    )
    after = _journal(directory, core["id"])
    assert (
        after["applied"]["revision_id"] == before["applied"]["revision_id"]
    ), "Unsafe candidate replaced installed revision"
    assert (
        after["usage_epochs"][-1]["id"] == before["usage_epochs"][-1]["id"]
    ), "Unsafe candidate replaced live process epoch"
    assert (
        _stats(runtime.binaries / "xray", stats_port, identity).returncode == 0
    ), "Unsafe candidate stopped prior live core"


def exercise_native_usage(
    directory,
    binary,
    binaries,
    base_url,
    admin_headers,
    node,
    cores,
    subscriptions,
    requests,
    ports,
    runtime,
    scheduler_raw,
    *,
    resource_report_policy: ResourceReportPolicy | None = None,
):
    config = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "proxy/runtime.config.sample.json"
        ).read_text()
    )
    config.update(
        enabled=True,
        api_url=base_url,
        node_code=node["node"]["code"],
        state_directory=str(directory / "usage-journal"),
        binaries={
            "xray": str(binaries / "xray"),
            "sing_box": str(binaries / "sing-box"),
        },
        poll_interval_ms=50,
        http_timeout_ms=2000,
        startup_grace_ms=150,
        max_cores=8,
        max_processes=8,
    )
    config["provisioning"].update(
        mode="installed_only", max_memberships=16, max_receipts=32
    )
    config["usage"].update(
        mode="observe",
        poll_interval_ms=300,
        rpc_timeout_ms=1000,
        max_profiles=32,
        max_profiles_per_poll=8,
        requested_bytes=3000000,
        activation_grace_ms=30000,
    )
    path = directory / "usage-agent.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    log_path = directory / "usage-agent.log"
    started = time.monotonic()
    with (
        httpx.Client(
            base_url=base_url,
            headers=admin_headers,
            timeout=10,
            trust_env=False,
            follow_redirects=False,
        ) as api,
        httpx.Client(
            base_url=base_url,
            headers={
                "X-Papilio-Node-Key": node["agent_key"],
                "X-Papilio-Node-Code": node["node"]["code"],
            },
            timeout=10,
            trust_env=False,
            follow_redirects=False,
        ) as node_api,
        log_path.open("w+") as log,
    ):
        log_path.chmod(0o600)
        process = subprocess.Popen(
            [str(binary), "-config", str(path)],
            env={**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]},
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            inventory = _data(
                api.get(
                    f"/v1/admin/network/nodes/{node['node']['id']}/cores",
                    params={"per_page": 16},
                ),
                "Native node inventory read failed",
            )
            assert len(inventory) <= config["max_cores"], (
                "Owned inventory exceeds capacity"
            )
            for owned in inventory:
                _stop_core(
                    api,
                    f"/v1/admin/network/cores/{owned['id']}/runtime",
                    process,
                )
            for core in cores:
                _empty_apply(api, core, process)
            outcomes = [
                exercise_native_installed_purchase(
                    scheduler_raw, request["id"]
                )
                for request in requests
            ]
            assert all(
                row[0] == "active" and row[1] == "applied" for row in outcomes
            ), "Native scheduler purchase failed"
            profiles = [_profile(api, request["id"]) for request in requests]
            outbounds = [
                runtime.client(_uri(api, profile["profile_id"]))
                for profile in profiles
            ]
            for index, outbound in enumerate(outbounds):
                runtime.exercise(
                    f"usage-real-{index}", outbound, accepted=True
                )
            grants = [
                _wait(
                    lambda sid=sub["id"]: _usage_rows(api, sid),
                    lambda rows: (
                        len(rows) == 1
                        and rows[0]["upload_bytes"] + rows[0]["download_bytes"]
                        > 0
                    ),
                    "Real native counters absent",
                )
                for sub in subscriptions
            ]
            allocated = [rows[0]["allocated_bytes"] for rows in grants]
            assert allocated == [1000000, 2000000], (
                "Purchased grant capacities ignored"
            )
            states = [
                _data(
                    api.get(f"/v1/admin/network/cores/{core['id']}/runtime"),
                    "Native usage state read failed",
                )
                for core in cores
            ]
            bindings = []
            for index, core in enumerate(cores):
                state = _journal(directory, core["id"])
                epoch = state["usage_epochs"][-1]
                binding = epoch["profiles"][0]["binding"]
                bindings.append(binding)
                assert (
                    states[index]["observed_process_epoch"] == epoch["id"]
                ), "Native running epoch differs"
                assert (
                    grants[index][0]["process_epoch"] == epoch["id"]
                    and grants[index][0]["usage_sha256"]
                    == epoch["usage_sha256"]
                ), "Native grant proof differs"
                response = _stats(
                    binaries / "xray",
                    ports[core["id"]],
                    binding["counter_identity"],
                )
                assert response.returncode == 0, (
                    "Native management Stats RPC unavailable"
                )
                values = json.loads(response.stdout).get("stat", [])
                assert (
                    len(values) == 2
                    and sum(int(item.get("value", 0)) for item in values) > 0
                ), "Native Stats counters missing"
                for target_index, target in enumerate(cores):
                    _subscriber_rpc(
                        runtime,
                        outbounds[index],
                        "127.0.0.1",
                        ports[target["id"]],
                        bindings[0]["counter_identity"],
                        f"usage-deny-{index}-{target_index}",
                    )
                _subscriber_rpc(
                    runtime,
                    outbounds[index],
                    "localhost",
                    ports[core["id"]],
                    binding["counter_identity"],
                    f"usage-domain-deny-{index}",
                )
                _subscriber_rpc(
                    runtime,
                    outbounds[index],
                    "example.com",
                    ports[core["id"]],
                    binding["counter_identity"],
                    f"usage-port-deny-{index}",
                )
            _wait(
                lambda: _data(
                    api.get(
                        f"/v1/admin/network/cores/{cores[0]['id']}/runtime"
                    ),
                    "Heartbeat read failed",
                ),
                lambda state: (
                    state["last_observed_at"] != states[0]["last_observed_at"]
                    and state["observed_process_epoch"]
                    == states[0]["observed_process_epoch"]
                ),
                "Live epoch heartbeat did not refresh",
            )
            for index, core in enumerate(cores):
                _wait(
                    lambda i=index, c=core: (
                        _usage_rows(api, subscriptions[i]["id"])[0],
                        _stats(
                            binaries / "xray",
                            ports[c["id"]],
                            bindings[i]["counter_identity"],
                        ),
                    ),
                    lambda pair: (
                        pair[1].returncode == 0
                        and (
                            pair[0]["upload_bytes"] + pair[0]["download_bytes"]
                            == sum(
                                int(item.get("value", 0))
                                for item in json.loads(pair[1].stdout).get(
                                    "stat", []
                                )
                            )
                        )
                    ),
                    "Native reports did not catch up to quiescent counters",
                )
            for core, subscription in zip(cores, subscriptions, strict=True):
                _replay_real_report(
                    api, node_api, directory, core, subscription
                )
            consumed = [
                _data(
                    api.get(f"/v1/admin/subscriptions/{sub['id']}"),
                    "Fresh consumed usage read failed",
                )["used_bytes"]
                for sub in subscriptions
            ]
            summaries = [
                _data(
                    api.get(
                        "/v1/admin/usage/summary",
                        params={"subscription_id": sub["id"]},
                    ),
                    "Fresh usage summary failed",
                )
                for sub in subscriptions
            ]
            assert consumed == [row["total_bytes"] for row in summaries], (
                "Native usage totals do not match consumed bytes"
            )
            metrics: ResourceMetrics = {
                **_sample_owned(process),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "profile_count": 2,
                "scope": (
                    "point-in-time Go and observed descendants; "
                    "no scale/minimum-memory claim"
                ),
            }
            resource_report = sample_resource_report(
                resource_report_policy, metrics
            )
            metric_path = directory / "usage-metrics.json"
            metric_path.write_text(json.dumps(metrics))
            metric_path.chmod(0o600)
            _unsafe_redirect_reproduction(
                runtime,
                directory,
                cores[0],
                outbounds[0],
                bindings[0]["counter_identity"],
            )
            _unmapped_refusal(api, runtime, node, "xray")
            _unmapped_refusal(api, runtime, node, "sing_box")
            _redirect_refusal(
                api,
                runtime,
                directory,
                cores[0],
                ports[cores[0]["id"]],
                bindings[0]["counter_identity"],
            )
            for core in cores:
                _stop_core(
                    api,
                    f"/v1/admin/network/cores/{core['id']}/runtime",
                    process,
                )
            final_grants = [
                _usage_rows(api, sub["id"])[0] for sub in subscriptions
            ]
            assert all(not row["is_closed"] for row in final_grants), (
                "Stop fabricated final usage"
            )
            return {
                "allocated_bytes": allocated,
                "used_bytes": consumed,
                "metrics": metrics,
                "resource_report": resource_report,
            }
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)


def _unsafe_redirect_reproduction(
    runtime, directory, core, outbound, identity
):
    """Pinned real-core reproduction outside managed agent/API installation.

    This proves the RPC tunnel can reach a service and that a post-routing
    rewrite bypasses a port guard. No unsafe native revision is installed.
    """
    state = _journal(directory, core["id"])
    installed = state["applied"]
    document = json.loads(
        (Path(installed["directory"]) / installed["filenames"][0]).read_text()
    )
    stats_port, subscriber_port = runtime.port(), runtime.port()
    for inbound in document["inbounds"]:
        inbound["port"] = (
            stats_port
            if inbound["tag"] == "papilio-stats-api"
            else subscriber_port
        )
    for egress in document["outbounds"]:
        if egress["protocol"] == "freedom":
            egress["settings"] = {"redirect": f"127.0.0.1:{stats_port}"}
    path = runtime.file(
        "unsafe-offline-redirect-server.json", json.dumps(document)
    )
    validation = subprocess.run(
        [str(runtime.binaries / "xray"), "run", "-test", "-config", str(path)],
        capture_output=True,
        timeout=5,
    )
    assert validation.returncode == 0, (
        "Pinned unsafe reproduction artifact not accepted"
    )
    process = runtime.start(
        "unsafe-offline-redirect-server",
        [str(runtime.binaries / "xray"), "run", "-config", str(path)],
    )
    try:
        _wait(
            lambda: (
                _stats(
                    runtime.binaries / "xray", stats_port, identity
                ).returncode
            ),
            lambda code: code == 0,
            "Offline reproduction management service unavailable",
            seconds=5,
        )
        subscriber = {**outbound, "server_port": subscriber_port}
        _subscriber_rpc(
            runtime,
            subscriber,
            "198.51.100.10",
            80,
            identity,
            "unsafe-offline-redirect-rpc",
            accepted=True,
        )
    finally:
        runtime.stop(process)


def _empty_apply(api, core, process):
    base = f"/v1/admin/network/cores/{core['id']}/runtime"
    state = _data(api.get(base), "Bootstrap state read failed")
    revision = _data(
        api.post(
            base + "/revisions",
            json={"expected_revision": state["revision"], "mode": "merged"},
        ),
        "Bootstrap guarded capture failed",
    )
    state = _data(api.get(base), "Bootstrap captured state read failed")
    command = _data(
        api.post(
            base + "/commands",
            json={
                "expected_revision": state["revision"],
                "action": "apply",
                "revision_id": revision["id"],
                "request_key": "usage_bootstrap_" + str(time.monotonic_ns()),
                "reason": "Owned guarded empty infrastructure bootstrap",
            },
        ),
        "Bootstrap apply queue failed",
    )

    def read():
        assert process.poll() is None, "Owned agent exited during bootstrap"
        rows = _data(
            api.get(base + "/commands", params={"per_page": 16}),
            "Bootstrap commands read failed",
        )
        return next(row for row in rows if row["id"] == command["id"])

    result = _wait(
        read,
        lambda row: row["state"] in {"succeeded", "failed"},
        "Bootstrap apply timeout",
    )
    assert result["state"] == "succeeded", (
        "Actual guarded bootstrap apply failed"
    )
    fresh = _data(api.get(base), "Bootstrap live state read failed")
    assert (
        fresh["observed_status"] == "running"
        and fresh["automation_paused"] is False
        and fresh["observed_process_epoch"]
    ), "Bootstrap lacks native live epoch/unpause"
