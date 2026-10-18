"""Quick installer command-line contract tests."""

import subprocess
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

    def test_script_has_valid_bash_syntax(self):
        subprocess.run(["bash", "-n", str(QUICK_INSTALL)], check=True)

    def test_missing_required_options_fail_before_network_or_secret_prompt(self):
        result = subprocess.run(
            ["bash", str(QUICK_INSTALL)],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("Set --public-url", result.stderr)

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
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("without a path", result.stderr)


if __name__ == "__main__":
    unittest.main()
