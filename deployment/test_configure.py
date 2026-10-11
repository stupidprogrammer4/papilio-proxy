"""Private Caddy transport regeneration without services or named volumes."""

import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import configure


class CaddyEnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state = Path(self.directory.name)
        self.source = self.state / "Caddyfile"
        configure.write_private(
            self.source, 'http://:8080 {\n respond "سلام $private"\n}\n'
        )
        configure.write_private(self.state / "secrets/owner-password", "fixture")

    def test_refresh_preserves_authoritative_edit_and_existing_identity(self):
        source = self.source.read_bytes()
        identity = (self.state / "secrets/owner-password").read_bytes()
        configure.refresh_caddy_environment(self.state)
        target = self.state / "web.env"
        values = configure.parse_env(configure.read_private(target))
        self.assertEqual(base64.b64decode(values["PAPILIO_CADDYFILE_BASE64"]), source)
        self.assertEqual(
            values["PAPILIO_CADDYFILE_SHA256"],
            hashlib.sha256(source).hexdigest(),
        )
        inode = target.stat().st_ino
        configure.refresh_caddy_environment(self.state)
        self.assertEqual(target.stat().st_ino, inode)
        self.source.write_text("http://:8080 {\n respond 204\n}\n")
        edited = self.source.read_bytes()
        configure.refresh_caddy_environment(self.state)
        values = configure.parse_env(configure.read_private(target))
        self.assertEqual(base64.b64decode(values["PAPILIO_CADDYFILE_BASE64"]), edited)
        self.assertEqual(self.source.read_bytes(), edited)
        self.assertEqual((self.state / "secrets/owner-password").read_bytes(), identity)
        if os.name != "nt":
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.stat().st_uid, self.source.stat().st_uid)
            self.assertEqual(target.stat().st_gid, self.source.stat().st_gid)

    @unittest.skipIf(os.name == "nt", "POSIX permission boundary")
    def test_nonprivate_source_and_derived_file_are_rejected(self):
        self.source.chmod(0o644)
        with self.assertRaises(ValueError):
            configure.refresh_caddy_environment(self.state)
        self.assertFalse((self.state / "web.env").exists())
        self.source.chmod(0o600)
        configure.refresh_caddy_environment(self.state)
        target = self.state / "web.env"
        previous = target.read_bytes()
        target.chmod(0o644)
        with self.assertRaises(ValueError):
            configure.refresh_caddy_environment(self.state)
        self.assertEqual(target.read_bytes(), previous)

    @unittest.skipIf(os.name == "nt", "POSIX symlink boundary")
    def test_symlinked_derived_file_cannot_overwrite_other_state(self):
        secret = self.state / "secrets/owner-password"
        (self.state / "web.env").symlink_to(secret)
        with self.assertRaises(ValueError):
            configure.refresh_caddy_environment(self.state)
        self.assertEqual(secret.read_text(), "fixture")


if __name__ == "__main__":
    unittest.main()
