"""A verified new source must use its own installer code for schema evolution."""

import json
import subprocess
import sys
from pathlib import Path

from deployment.papilio_installer.configuration import Installation, InstallSettings

PROJECT = Path(__file__).resolve().parents[2]


def test_update_hands_identity_and_source_to_the_new_installer(tmp_path: Path) -> None:
    old = tmp_path / "old"
    old.mkdir()
    (old / "VERSION").write_text("0.0.0-old\n")
    home = tmp_path / "home"
    Installation.create(
        home, old, InstallSettings(environment="test", instance="delegate", image_mode="build")
    )
    target = tmp_path / "next"
    (target / "deployment").mkdir(parents=True)
    (target / "VERSION").write_text("0.0.0-next\n")
    (target / "deployment/compose.yml").write_text("services: {}\n")
    marker = tmp_path / "entrypoint.json"
    (target / "deployment/papilio.py").write_text(
        "import json,sys\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(json.dumps(sys.argv[1:]))\n"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "deployment/papilio.py"),
            "--home",
            str(home),
            "--environment",
            "test",
            "--instance",
            "delegate",
            "update",
            "--source",
            str(target),
            "--image-mode",
            "prebuilt",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(marker.read_text()) == [
        "--home",
        str(home),
        "--environment",
        "test",
        "--instance",
        "delegate",
        "update",
        "--source",
        str(target),
        "--image-mode",
        "prebuilt",
    ]


def test_bootstrap_update_uses_existing_identity_without_install_prompts(tmp_path: Path) -> None:
    target = tmp_path / "next"
    (target / "deployment").mkdir(parents=True)
    (target / "VERSION").write_text("0.0.0-next\n")
    marker = tmp_path / "bootstrap.json"
    (target / "deployment/papilio.py").write_text(
        "import json,sys\nfrom pathlib import Path\n"
        f"Path({str(marker)!r}).write_text(json.dumps(sys.argv[1:]))\n"
    )
    home = tmp_path / "installation"
    result = subprocess.run(
        [
            "bash",
            str(PROJECT / "install.sh"),
            "--update",
            "--source",
            str(target),
            "--home",
            str(home),
            "--environment",
            "production",
            "--instance",
            "existing",
            "--image-mode",
            "prebuilt",
            "--non-interactive",
            "--allow-unverified-host",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(marker.read_text()) == [
        "--home",
        str(home),
        "--environment",
        "production",
        "--instance",
        "existing",
        "update",
        "--source",
        str(target),
        "--image-mode",
        "prebuilt",
    ]
