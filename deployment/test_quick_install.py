"""Quick installer command-line contract tests."""

import os
import pty
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUICK_INSTALL = ROOT / "scripts" / "deploy" / "quick-install.sh"


class QuickInstallTest(unittest.TestCase):
    def test_help_describes_one_line_install_and_private_credentials(self):
        result = subprocess.run(
            ["bash", str(QUICK_INSTALL), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )

        self.assertIn("--public-url", result.stdout)
        self.assertIn("--owner-username", result.stdout)
        self.assertIn("password", result.stdout.lower())
        self.assertIn("--enable-bot", result.stdout)
        self.assertIn("curl -fsSL", result.stdout)
        self.assertIn("If omitted, the installer asks", result.stdout)

    def test_script_has_valid_bash_syntax(self):
        subprocess.run(["bash", "-n", str(QUICK_INSTALL)], check=True)

    def test_noninteractive_invocation_without_tty_fails_before_network(self):
        result = subprocess.run(
            ["bash", str(QUICK_INSTALL)],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("interactive terminal", result.stderr)

    def test_bare_invocation_prompts_and_uses_private_tty(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            archive_path = temporary_path / "source.tar.gz"
            log_path = temporary_path / "install-arguments"
            fake_bin = temporary_path / "bin"
            fake_bin.mkdir()
            installer = (
                '#!/usr/bin/env bash\nprintf \'%s\\n\' "$@" > "$PAPILIO_INSTALL_LOG"\n'
            )
            with tarfile.open(archive_path, "w:gz") as archive:
                for name, contents in (
                    ("papilio-proxy-main/scripts/deploy/install.sh", installer),
                    ("papilio-proxy-main/deployment/compose.yml", "services: {}\n"),
                ):
                    file_path = temporary_path / name.split("/")[-1]
                    file_path.write_text(contents, encoding="utf-8")
                    if name.endswith("install.sh"):
                        file_path.chmod(0o755)
                    archive.add(file_path, arcname=name)

            (fake_bin / "curl").write_text(
                "#!/usr/bin/env bash\n"
                "while [ $# -gt 0 ]; do\n"
                '  if [ "$1" = --output ]; then cp "$PAPILIO_TEST_ARCHIVE" "$2"; exit; fi\n'
                "  shift\n"
                "done\n"
                "exit 1\n",
                encoding="utf-8",
            )
            (fake_bin / "docker").write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
            )
            for executable in fake_bin.iterdir():
                executable.chmod(0o700)

            previous_environment = os.environ.copy()
            os.environ.update(
                {
                    "HOME": str(temporary_path / "home"),
                    "PATH": f"{fake_bin}:{previous_environment['PATH']}",
                    "PAPILIO_TEST_ARCHIVE": str(archive_path),
                    "PAPILIO_INSTALL_LOG": str(log_path),
                    "PAPILIO_INSTALL_HOME": str(temporary_path / "install"),
                }
            )
            try:
                child_pid, terminal = pty.fork()
                if child_pid == 0:
                    os.execvp("bash", ["bash", str(QUICK_INSTALL)])

                output = bytearray()
                while b"Panel URL" not in output:
                    output.extend(os.read(terminal, 4096))
                os.write(terminal, b"https://panel.example.test\n")
                while b"Administrator username" not in output:
                    output.extend(os.read(terminal, 4096))
                os.write(terminal, b"\n")
                while True:
                    try:
                        output.extend(os.read(terminal, 4096))
                    except OSError:
                        break
                _, status = os.waitpid(child_pid, 0)
                os.close(terminal)
            finally:
                os.environ.clear()
                os.environ.update(previous_environment)

            self.assertEqual(os.waitstatus_to_exitcode(status), 0, output.decode())
            arguments = log_path.read_text(encoding="utf-8")
            self.assertIn("https://panel.example.test", arguments)
            self.assertIn("admin", arguments)

    def test_public_install_rejects_plain_http_before_download(self):
        result = subprocess.run(
            [
                "bash",
                str(QUICK_INSTALL),
                "--public-url",
                "http://panel.example.com",
                "--owner-username",
                "admin",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Use HTTPS for a public domain", result.stderr)

    def test_public_https_port_must_match_the_advertised_url(self):
        result = subprocess.run(
            [
                "bash",
                str(QUICK_INSTALL),
                "--public-url",
                "https://panel.example.com",
                "--https-port",
                "8443",
                "--owner-username",
                "admin",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("URL port and --https-port must match", result.stderr)

    def test_public_https_rejects_url_paths(self):
        result = subprocess.run(
            [
                "bash",
                str(QUICK_INSTALL),
                "--public-url",
                "https://panel.example.com/admin",
                "--owner-username",
                "admin",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("without a path", result.stderr)


if __name__ == "__main__":
    unittest.main()
