from pathlib import Path
from typing import Protocol

from src.modules.operations.backups.domain.contracts import (
    DatabaseSnapshot,
    RecoveryPayload,
    RestoreResult,
)


class IDatabaseRecovery(Protocol):
    @property
    def database_name(self) -> str: ...

    def snapshot(self) -> DatabaseSnapshot: ...

    def restore_empty(self, sql: str, revision: str) -> RestoreResult: ...


class IRecoveryArchives(Protocol):
    def create(
        self, database: IDatabaseRecovery, config_yaml: str, destination: Path
    ) -> RecoveryPayload: ...

    def read(self, source: Path) -> RecoveryPayload: ...

    def restore(
        self, source: Path, database: IDatabaseRecovery
    ) -> RestoreResult: ...

    def extract_config(self, source: Path, destination: Path) -> None: ...
