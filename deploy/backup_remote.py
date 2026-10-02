"""Create an encrypted, off-node VPS backup and verify a MySQL restore locally.

Run on the owner's workstation with ``python deploy/backup_remote.py``. The
private .env must contain IPV4, SSH_PASSWORD, SSH_HOST_KEY_SHA256 and
CREDENTIAL_ENCRYPTION_KEY. Neither the SQL dump nor secrets touch local disk
unencrypted. This is a manual snapshot, not an automatic backup schedule.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import secrets
import subprocess
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import paramiko
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ROOT = Path(__file__).resolve().parents[1]
MAX_DUMP_BYTES = 64 * 1024 * 1024
REMOTE = "/opt/papilio-proxy"
FILES = (
    ".env",
    "compose.yaml",
    "data/xray/config.json",
    "data/xray/node.json",
    "data/xray/certs/fullchain.pem",
    "data/xray/certs/privkey.pem",
    "data/hysteria/node.json",
    "data/hysteria/server.json",
)


def _settings() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("IPV4", "SSH_PASSWORD", "SSH_HOST_KEY_SHA256", "CREDENTIAL_ENCRYPTION_KEY"):
        if not values.get(key):
            raise RuntimeError(f"Backup setting {key} is missing")
    return values


class _PinnedKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected: str) -> None:
        self.expected = expected.removeprefix("SHA256:").rstrip("=")

    def missing_host_key(
        self, client: paramiko.SSHClient, hostname: str, key: paramiko.PKey
    ) -> None:
        actual = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        if not secrets.compare_digest(actual, self.expected):
            raise paramiko.SSHException("Server SSH host key changed")


def _cipher(key: str) -> Fernet:
    raw = base64.urlsafe_b64decode(key.encode())
    if len(raw) != 32:
        raise RuntimeError("Invalid credential encryption key")
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"papilio-off-node-backup-v1",
        info=b"fernet-snapshot",
    ).derive(raw)
    return Fernet(base64.urlsafe_b64encode(derived))


def _fetch_archive(settings: dict[str, str]) -> bytes:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(_PinnedKey(settings["SSH_HOST_KEY_SHA256"]))
    client.connect(
        settings["IPV4"], username=settings.get("SSH_USER", "root"),
        password=settings["SSH_PASSWORD"], timeout=15,
        look_for_keys=False, allow_agent=False,
    )
    try:
        command = (
            f"cd {REMOTE} && docker compose exec -T mysql sh -c "
            "'MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" mysqldump -uroot "
            "--single-transaction --quick --routines --events --no-tablespaces papilio'"
        )
        _, stdout, stderr = client.exec_command(command, timeout=120)
        dump = stdout.read(MAX_DUMP_BYTES + 1)
        if len(dump) > MAX_DUMP_BYTES:
            stdout.channel.close()
            raise RuntimeError("Database exceeds the bounded manual backup size")
        if stdout.channel.recv_exit_status() != 0 or not dump.startswith(b"-- MySQL dump"):
            _ = stderr.read(4096)
            raise RuntimeError("Remote MySQL dump failed")
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("mysql/papilio.sql", dump)
            with client.open_sftp() as sftp:
                for relative in FILES:
                    with sftp.open(f"{REMOTE}/{relative}", "rb") as source:
                        bundle.writestr(relative, source.read())
        return archive.getvalue()
    finally:
        client.close()


def _verify_restore(encrypted: bytes, cipher: Fernet) -> None:
    with zipfile.ZipFile(io.BytesIO(cipher.decrypt(encrypted))) as archive:
        if archive.testzip() is not None:
            raise RuntimeError("Backup archive checksum failed")
        if any(name not in archive.namelist() for name in (*FILES, "mysql/papilio.sql")):
            raise RuntimeError("Backup archive is incomplete")
        dump = archive.read("mysql/papilio.sql")
    name = "papilio-restore-" + secrets.token_hex(4)
    password = secrets.token_urlsafe(24)
    environment = {**os.environ, "MYSQL_ROOT_PASSWORD": password}
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name,
         "--tmpfs", "/var/lib/mysql:rw,size=1g", "-e", "MYSQL_ROOT_PASSWORD",
         "-e", "MYSQL_DATABASE=papilio", "mysql:8.4"],
        env=environment, stdout=subprocess.DEVNULL, check=True, timeout=30,
    )
    try:
        ping = ["docker", "exec", name, "sh", "-c",
                'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqladmin -uroot status']
        for _ in range(90):
            logs = subprocess.run(["docker", "logs", name], capture_output=True,
                                  check=False, timeout=5)
            initialized = b"MySQL init process done" in logs.stdout + logs.stderr
            if initialized and subprocess.run(
                ping, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
            ).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Temporary MySQL did not start")
        restore = subprocess.run(
            ["docker", "exec", "-i", name, "sh", "-c",
             'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot papilio'],
            input=dump, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            check=False, timeout=120,
        )
        if restore.returncode != 0:
            match = re.search(rb"ERROR ([0-9]+)", restore.stderr)
            code = match.group(1).decode() if match else "unknown"
            raise RuntimeError(f"MySQL restore failed (error code {code})")
        check = subprocess.run(
            ["docker", "exec", name, "sh", "-c",
             'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --no-create-info papilio'],
            capture_output=True, check=False, timeout=60,
        )
        if check.returncode != 0 or b"`subscriptions`" not in check.stdout:
            raise RuntimeError("Restored MySQL tables did not round-trip")
    finally:
        subprocess.run(["docker", "stop", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=30)


def main() -> None:
    settings = _settings()
    cipher = _cipher(settings["CREDENTIAL_ENCRYPTION_KEY"])
    encrypted = cipher.encrypt(_fetch_archive(settings))
    destination = ROOT / "data/backups"
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    filename = "papilio-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + ".zip.fernet"
    path = destination / filename
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(encrypted)
    _verify_restore(encrypted, cipher)
    print(f"Encrypted off-node backup and isolated restore verified: {path}")


if __name__ == "__main__":
    main()
