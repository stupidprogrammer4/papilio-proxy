"""Deployment backup entrypoint tests."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "scripts" / "deploy" / "backup.sh"


class DeploymentBackupTest(unittest.TestCase):
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
            "[ \"$3\" = --help ]; then printf -- '--wait-timeout'; exit 0; fi\n"
            'printf \'%s\\n\' "$@" >> "$PAPILIO_DOCKER_LOG"\n',
            encoding="utf-8",
        )
        docker.chmod(0o700)

    def test_backup_uses_owned_project_and_verifies_encrypted_archive(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state = root / "state"
            state.mkdir()
            (state / "compose.env").write_text(
                "PROJECT_NAME=backup-test\n"
                "PUBLIC_URL=http://127.0.0.1:8080\n"
                "BOT_ENABLED=false\n"
                "START_TIMEOUT=60\n",
                encoding="utf-8",
            )
            key = root / "recovery.key"
            key.write_text("r" * 64, encoding="utf-8")
            key.chmod(0o600)
            output_directory = root / "offsite"
            output_directory.mkdir()
            output = output_directory / "papilio.encrypted"
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
                    str(BACKUP),
                    "--state-dir",
                    str(state),
                    "--key-file",
                    str(key),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = docker_log.read_text(encoding="utf-8")
            self.assertIn("run\n--rm\n--no-deps", arguments)
            self.assertIn(f"{key}:/run/papilio-recovery.key:ro", arguments)
            self.assertIn(f"{output_directory}:/backup", arguments)
            self.assertIn("scripts/recovery.py", arguments)
            self.assertIn("create", arguments)
            self.assertIn("verify", arguments)
            self.assertIn("/app/config.yml", arguments)
            self.assertIn("/backup/papilio.encrypted", arguments)

    def test_existing_archive_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            state = root / "state"
            state.mkdir()
            (state / "compose.env").write_text(
                "PROJECT_NAME=backup-test\n"
                "PUBLIC_URL=http://127.0.0.1:8080\n"
                "BOT_ENABLED=false\n"
                "START_TIMEOUT=60\n",
                encoding="utf-8",
            )
            key = root / "recovery.key"
            key.write_text("r" * 64, encoding="utf-8")
            key.chmod(0o600)
            output = root / "existing.encrypted"
            output.write_bytes(b"keep existing backup")
            docker_log = root / "docker-arguments"
            fake_bin = root / "bin"
            fake_bin.mkdir()
            self.write_docker_stub(fake_bin)
            environment = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "PAPILIO_DOCKER_LOG": str(docker_log),
            }

            result = subprocess.run(
                [
                    "bash",
                    str(BACKUP),
                    "--state-dir",
                    str(state),
                    "--key-file",
                    str(key),
                    "--output",
                    str(output),
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("already exists", result.stderr)
            self.assertEqual(output.read_bytes(), b"keep existing backup")
            self.assertFalse(docker_log.exists())


if __name__ == "__main__":
    unittest.main()
