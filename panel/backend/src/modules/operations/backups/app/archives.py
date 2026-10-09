import os
from datetime import UTC, datetime
from pathlib import Path

import yaml
from papilio.security.crypto import decrypt, encrypt, hash_sha256

from src.modules.operations.backups.domain.contracts import (
    RecoveryPayload,
    RecoverySettings,
    RestoreResult,
)
from src.modules.operations.backups.interfaces import IDatabaseRecovery


class RecoveryArchives:
    def __init__(self, settings: RecoverySettings, key: str) -> None:
        if len(key) < 32:
            raise ValueError(
                "Use an independent recovery key of 32+ characters"
            )
        self.settings = settings
        self.key = key

    def create(
        self, database: IDatabaseRecovery, config_yaml: str, destination: Path
    ) -> RecoveryPayload:
        self.validate_config(config_yaml)
        snapshot = database.snapshot()
        payload = RecoveryPayload(
            format_version=1,
            created_at=datetime.now(UTC),
            source_database=database.database_name,
            consistency=self.settings.consistency,
            schema_revision=snapshot.schema_revision,
            config_yaml=config_yaml,
            sql_sha256=hash_sha256(snapshot.sql),
            sql=snapshot.sql,
        )
        serialized = payload.model_dump_json()
        if len(serialized.encode()) > self.settings.max_payload_bytes:
            raise ValueError("Backup payload exceeds configured capacity")
        encrypted = encrypt(serialized, self.key)
        if len(encrypted.encode()) > self.settings.max_archive_bytes:
            raise ValueError("Backup archive exceeds configured capacity")
        self.write_private(destination, encrypted)
        return payload

    def read(self, source: Path) -> RecoveryPayload:
        with source.open("rb") as stream:
            encrypted = stream.read(self.settings.max_archive_bytes + 1)
        if len(encrypted) > self.settings.max_archive_bytes:
            raise ValueError("Backup archive exceeds configured capacity")
        serialized = decrypt(encrypted.decode("ascii"), self.key)
        if len(serialized.encode()) > self.settings.max_payload_bytes:
            raise ValueError("Backup payload exceeds configured capacity")
        payload = RecoveryPayload.model_validate_json(serialized)
        if (
            len(payload.sql.encode()) > self.settings.max_sql_bytes
            or hash_sha256(payload.sql) != payload.sql_sha256
        ):
            raise ValueError("SQL snapshot integrity or capacity check failed")
        self.validate_config(payload.config_yaml)
        return payload

    def restore(
        self, source: Path, database: IDatabaseRecovery
    ) -> RestoreResult:
        payload = self.read(source)
        result = database.restore_empty(payload.sql, payload.schema_revision)
        return result

    def extract_config(self, source: Path, destination: Path) -> None:
        payload = self.read(source)
        self.write_private(destination, payload.config_yaml)

    @staticmethod
    def validate_config(config_yaml: str) -> None:
        from src.config.settings import PapilioSettings

        PapilioSettings.model_validate(yaml.safe_load(config_yaml))

    @staticmethod
    def write_private(destination: Path, value: str) -> None:
        descriptor = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
