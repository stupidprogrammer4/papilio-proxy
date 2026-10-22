"""Exercise Bash prerequisite decisions with isolated external command doubles."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("document", ("README.md", "README.fa.md"))
def test_public_command_skips_package_manager_when_downloader_is_ready(document: str) -> None:
    command = next(
        line
        for line in (PROJECT / document).read_text().splitlines()
        if line.startswith("sudo bash -c ")
    )
    arguments = shlex.split(command)
    # Substitute only external package/download boundaries; execute the documented Bash.
    setup = (
        "apt-get() { echo UNNECESSARY_APT >&2; return 99; }; "
        "curl() { printf 'printf BOOTSTRAP_REACHED'; }; "
    )
    result = subprocess.run(
        ["bash", "-c", setup + arguments[3]], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "BOOTSTRAP_REACHED"
    assert "UNNECESSARY_APT" not in result.stderr


@pytest.mark.parametrize("missing_dependencies", (False, True))
def test_docker_refreshes_only_its_repository_unless_dependencies_need_indexes(
    tmp_path: Path, missing_dependencies: bool
) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("uname", "realpath", "mktemp", "rm", "install", "chmod", "cat", "grep"):
        target = shutil.which(name)
        assert target is not None
        (binaries / name).symlink_to(target)
    log = tmp_path / "calls.jsonl"
    source = tmp_path / "source"
    source.mkdir()
    apt_root = tmp_path / "etc/apt"
    (apt_root / "sources.list.d").mkdir(parents=True)
    script = tmp_path / "install.sh"
    # Simulate privilege and relocate configuration; never touch the host's APT state.
    script.write_text(
        (PROJECT / "install.sh")
        .read_text()
        .replace("/etc/apt/", f"{apt_root}/")
        .replace("$EUID", "0")
    )
    doubles = {
        "python3": "#!/bin/sh\nexit 0\n",
        "dpkg-query": "#!/bin/sh\nexit 1\n",
        "dpkg": "#!/bin/sh\nprintf amd64\n",
        "curl": '#!/bin/sh\nwhile [ "$1" != --output ]; do shift; done\nprintf key > "$2"\n',
        "apt-get": (
            f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
            f"with Path({str(log)!r}).open('a') as stream: "
            "stream.write(json.dumps(sys.argv[1:])+'\\n')\n"
            f"sys.exit(100 if '--simulate' in sys.argv and {missing_dependencies!r} else 0)\n"
        ),
    }
    for name, body in doubles.items():
        executable = binaries / name
        executable.write_text(body)
        executable.chmod(0o755)
    result = subprocess.run(
        [
            "/bin/bash",
            str(script),
            "--source",
            str(source),
            "--non-interactive",
            "--environment",
            "sandbox",
            "--allow-unverified-host",
        ],
        env=os.environ | {"PATH": str(binaries)},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    updates = [call for call in calls if "update" in call]
    assert len(updates) == (2 if missing_dependencies else 1)
    assert f"Dir::Etc::sourcelist={apt_root}/sources.list.d/docker.sources" in updates[0]
    assert "Dir::Etc::sourceparts=-" in updates[0]
    assert "APT::Get::List-Cleanup=0" in updates[0]
    assert calls[-1] == [
        "install",
        "-y",
        "docker-ce",
        "docker-ce-cli",
        "containerd.io",
        "docker-buildx-plugin",
        "docker-compose-plugin",
    ]
    assert ["install", "-y", "ca-certificates", "curl"] not in calls
