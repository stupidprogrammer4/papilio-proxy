"""Panel lifecycle delegates node operations without loading panel instance data."""

import subprocess
import sys
from pathlib import Path


def test_panel_command_exposes_native_node_installation_and_lifecycle() -> None:
    source = Path(__file__).resolve().parents[2]
    for arguments in (("node", "--help"), ("node", "install", "--help")):
        result = subprocess.run(
            [sys.executable, str(source / "deployment/papilio.py"), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        if arguments[-2] == "install":
            assert "--bootstrap" in result.stdout and "--prepare-only" in result.stdout
        else:
            assert "install" in result.stdout and "restart" in result.stdout
