import json
import os
import subprocess
from pathlib import Path


def publish_actual_capabilities(
    directory: Path,
    binary: Path,
    binaries: Path,
    base_url: str,
    node: dict,
) -> dict:
    repository = Path(__file__).resolve().parents[3]
    config = json.loads(
        (repository / "proxy/runtime.config.sample.json").read_text()
    )
    config.update(
        enabled=False,
        api_url=base_url,
        node_code=node["node"]["code"],
        state_directory=str(directory / "unused-runtime-journal"),
        binaries={
            "xray": str(binaries / "xray"),
            "sing_box": str(binaries / "sing-box"),
        },
    )
    config["capability_submission"].update(
        enabled=True, state_directory=str(directory / "capability-outbox")
    )
    path = directory / "agent.json"
    path.write_text(json.dumps(config))
    path.chmod(0o600)
    reply = subprocess.run(
        [str(binary), "-config", str(path), "-publish-capabilities"],
        env={**os.environ, "PAPILIO_NODE_KEY": node["agent_key"]},
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert reply.returncode == 0, "Owned capability publication failed"
    assert not reply.stderr, "Owned capability publication emitted errors"
    receipt = json.loads(reply.stdout)
    assert not (directory / "unused-runtime-journal").exists()
    assert not (directory / "capability-outbox/pending.json").exists()
    return receipt
