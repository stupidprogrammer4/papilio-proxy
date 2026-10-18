"""Deployment preflight reports native Compose health without mutation."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "scripts" / "deploy" / "doctor.sh"


class DeploymentDoctorTest(unittest.TestCase):
    def run_doctor(self, rows: str, bot_enabled: str = "false"):
        temporary = tempfile.TemporaryDirectory(prefix="papilio doctor ")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        state = root / "state"
        state.mkdir()
        (state / "compose.env").write_text(
            "PROJECT_NAME=fixture\n"
            f"BOT_ENABLED={bot_enabled}\n"
            "START_TIMEOUT=30\n"
            "PUBLIC_URL=http://127.0.0.1:18080\n",
            encoding="utf-8",
        )
        fake_bin = root / "bin"
        fake_bin.mkdir()
        docker = fake_bin / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "$1" = compose ]; then\n'
            '  if [ "$2" = version ]; then exit 0; fi\n'
            "  if [ \"$2\" = up ]; then printf '%s\\n' --wait-timeout; exit 0; fi\n"
            '  cat "$PAPILIO_DOCTOR_ROWS"\n'
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = info ]; then printf 'linux\\n'; exit 0; fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        docker.chmod(0o700)
        rows_path = root / "rows"
        rows_path.write_text(rows, encoding="utf-8")
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{fake_bin}:{environment['PATH']}",
                "PAPILIO_DOCTOR_ROWS": str(rows_path),
            }
        )
        return subprocess.run(
            ["bash", str(DOCTOR), "--state-dir", str(state)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_healthy_stack_reports_external_capabilities_as_unchecked(self):
        rows = """\
api;running;healthy
mysql;running;healthy
redis;running;healthy
nats;running;healthy
events-worker;running;healthy
worker;running;
scheduler;running;
web;running;healthy
"""
        result = self.run_doctor(rows)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("API: healthy", result.stdout)
        self.assertIn("Worker: running (no healthcheck)", result.stdout)
        self.assertIn("OCR provider: not checked by this command", result.stdout)
        self.assertIn("Node runtime: not checked by this command", result.stdout)
        self.assertIn("Payment source: not checked by this command", result.stdout)

    def test_unhealthy_required_service_returns_failure_and_names_service(self):
        rows = """\
api;running;healthy
mysql;running;healthy
redis;running;unhealthy
nats;running;healthy
events-worker;running;healthy
worker;running;
scheduler;running;
web;running;healthy
"""
        result = self.run_doctor(rows)

        self.assertEqual(result.returncode, 1)
        self.assertIn("Redis: unhealthy", result.stdout)

    def test_enabled_bot_is_required_and_its_health_is_reported(self):
        rows = """\
api;running;healthy
mysql;running;healthy
redis;running;healthy
nats;running;healthy
events-worker;running;healthy
worker;running;
scheduler;running;
web;running;healthy
bot;exited;
"""
        result = self.run_doctor(rows, bot_enabled="true")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Telegram bot: unavailable (exited)", result.stdout)


if __name__ == "__main__":
    unittest.main()
