"""Deployment restore entrypoint tests."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESTORE = ROOT / "scripts" / "deploy" / "restore.sh"


class DeploymentRestoreTest(unittest.TestCase):
    @staticmethod
    def write_docker_stub(fake_bin: Path) -> None:
        docker = fake_bin / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = info ]; then printf linux; exit 0; fi\n'
            'if [ "$1" = ps ] || [ "$1" = volume ] || '
            '[ "$1" = network ]; then exit 0; fi\n'
            'if [ "$1" = compose ] && [ "$2" = version ]; then '
            "printf 'Docker Compose version v2'; exit 0; fi\n"
            'if [ "$1" = compose ] && [ "$2" = up ] && '
            '[ "$3" = --help ]; then printf -- "--wait-timeout"; exit 0; fi\n'
            'printf \'%s\\n\' "$*" >> "$PAPILIO_DOCKER_LOG"\n',
            encoding="utf-8",
        )
        docker.chmod(0o700)

    def test_restore_verifies_then_stops_writers_restores_and_starts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state = root / "state"
            state.mkdir()
            (state / "compose.env").write_text(
                "PROJECT_NAME=restore-test\n"
                "PUBLIC_URL=http://127.0.0.1:8080\n"
                "BOT_ENABLED=true\n"
                "START_TIMEOUT=60\n",
                encoding="utf-8",
            )
            key = root / "recovery.key"
            key.write_text("r" * 64, encoding="utf-8")
            key.chmod(0o600)
            archive_directory = root / "offsite"
            archive_directory.mkdir()
            archive = archive_directory / "papilio.encrypted"
            archive.write_bytes(b"encrypted archive")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            docker_log = root / "docker-arguments"
            self.write_docker_stub(fake_bin)
            environment = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "PAPILIO_DOCKER_LOG": str(docker_log),
            }

            result = subprocess.run(
                [
                    "bash",
                    str(RESTORE),
                    "--state-dir",
                    str(state),
                    "--key-file",
                    str(key),
                    "--archive",
                    str(archive),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            commands = docker_log.read_text(encoding="utf-8").splitlines()
            verify = next(
                i for i, line in enumerate(commands) if " verify " in f" {line} "
            )
            stop = next(i for i, line in enumerate(commands) if " stop " in f" {line} ")
            restore = next(
                i for i, line in enumerate(commands) if " restore " in f" {line} "
            )
            restart = next(
                (
                    i
                    for i, line in enumerate(commands[restore + 1 :], restore + 1)
                    if "check_gateway.py" in line
                ),
                None,
            )
            self.assertLess(verify, stop)
            self.assertLess(stop, restore)
            self.assertIsNotNone(
                restart, f"{result.stdout}\n{result.stderr}\n{commands}"
            )
            self.assertLess(restore, restart)
            self.assertIn("events-worker", commands[stop])
            self.assertIn("worker", commands[stop])
            self.assertIn("scheduler", commands[stop])
            bot_stop = next(
                i for i, line in enumerate(commands) if "--profile bot stop bot" in line
            )
            self.assertLess(bot_stop, restore)
            self.assertIn(f"{key}:/run/papilio-recovery.key:ro", commands[restore])
            self.assertIn(f"{archive_directory}:/backup:ro", commands[restore])
            self.assertIn("/backup/papilio.encrypted", commands[restore])
            self.assertIn("--target-config /app/config.yml", commands[restore])

    def test_missing_archive_fails_before_docker_or_runtime_changes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state = root / "state"
            state.mkdir()
            (state / "compose.env").write_text(
                "PROJECT_NAME=restore-test\n"
                "PUBLIC_URL=http://127.0.0.1:8080\n"
                "BOT_ENABLED=false\n"
                "START_TIMEOUT=60\n",
                encoding="utf-8",
            )
            key = root / "recovery.key"
            key.write_text("r" * 64, encoding="utf-8")
            key.chmod(0o600)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            docker_log = root / "docker-arguments"
            self.write_docker_stub(fake_bin)
            environment = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "PAPILIO_DOCKER_LOG": str(docker_log),
            }

            result = subprocess.run(
                [
                    "bash",
                    str(RESTORE),
                    "--state-dir",
                    str(state),
                    "--key-file",
                    str(key),
                    "--archive",
                    str(root / "missing.encrypted"),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("regular, non-symlink file", result.stderr)
            self.assertFalse(docker_log.exists())


if __name__ == "__main__":
    unittest.main()
