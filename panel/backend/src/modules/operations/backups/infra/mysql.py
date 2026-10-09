import os
import re
import selectors
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Iterator

from sqlalchemy.engine import make_url

from src.modules.operations.backups.domain.contracts import (
    DatabaseSnapshot,
    RecoverySettings,
    RestoreResult,
)


class MySQLRecovery:
    def __init__(self, dsn: str, settings: RecoverySettings) -> None:
        self.url = make_url(dsn)
        if self.url.get_backend_name() != "mysql":
            raise ValueError("Recovery requires MySQL")
        if (
            not self.url.database
            or not re.fullmatch(r"[A-Za-z0-9_]+", self.url.database)
            or not self.url.host
            or not self.url.username
        ):
            raise ValueError("Recovery requires an explicit MySQL database")
        self.settings = settings

    @property
    def database_name(self) -> str:
        assert self.url.database is not None
        return self.url.database

    @contextmanager
    def connection_files(self) -> Iterator[tuple[list[str], Path]]:
        with TemporaryDirectory(
            prefix="papilio-recovery-",
            dir=self.settings.temporary_directory,
        ) as temporary:
            directory = Path(temporary)
            credentials = directory / "client.cnf"
            descriptor = os.open(
                credentials, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w") as stream:
                stream.write(
                    "[client]\nuser="
                    + _option(self.url.username or "")
                    + "\npassword="
                    + _option(self.url.password or "")
                    + "\n"
                )
            arguments = [
                f"--defaults-extra-file={credentials}",
                "--protocol=TCP",
                f"--host={self.url.host}",
                f"--port={self.url.port or 3306}",
                "--default-character-set=utf8mb4",
            ]
            yield arguments, directory

    def query(self, arguments: list[str], directory: Path, sql: str) -> str:
        output = directory / "query.txt"
        self.run_file(
            [
                self.settings.mysql_executable,
                *arguments,
                "--batch",
                "--skip-column-names",
                "--local-infile=0",
                "--skip-reconnect",
                self.database_name,
                "-e",
                sql,
            ],
            output,
            self.settings.max_payload_bytes,
        )
        return output.read_text().strip()

    def run_file(
        self, arguments: list[str], destination: Path, capacity: int
    ) -> None:
        with subprocess.Popen(
            arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        ) as process:
            assert process.stdout is not None
            deadline = monotonic() + self.settings.command_timeout_seconds
            try:
                with (
                    selectors.DefaultSelector() as selector,
                    destination.open("wb") as output,
                ):
                    selector.register(process.stdout, selectors.EVENT_READ)
                    written = 0
                    while True:
                        remaining = deadline - monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise ValueError(
                                "MySQL recovery command timed out"
                            )
                        content = os.read(
                            process.stdout.fileno(),
                            min(
                                self.settings.io_chunk_bytes,
                                capacity + 1 - written,
                            ),
                        )
                        if not content:
                            break
                        written += len(content)
                        if written > capacity:
                            raise ValueError(
                                "Recovery output exceeds capacity"
                            )
                        output.write(content)
                remaining = deadline - monotonic()
                if remaining <= 0 or process.wait(timeout=remaining) != 0:
                    raise ValueError("MySQL recovery command failed")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()

    def run(self, arguments: list[str], **kwargs) -> None:
        try:
            subprocess.run(
                arguments,
                check=True,
                timeout=self.settings.command_timeout_seconds,
                stderr=subprocess.DEVNULL,
                **kwargs,
            )
        except (subprocess.SubprocessError, OSError) as error:
            raise ValueError("MySQL recovery command failed") from error

    def snapshot(self) -> DatabaseSnapshot:
        with self.connection_files() as (arguments, directory):
            objects = self.query(
                arguments,
                directory,
                "SELECT (SELECT COUNT(*) FROM information_schema.views "
                "WHERE table_schema=DATABASE()) + "
                "(SELECT COUNT(*) FROM information_schema.triggers "
                "WHERE trigger_schema=DATABASE()) + "
                "(SELECT COUNT(*) FROM information_schema.routines "
                "WHERE routine_schema=DATABASE()) + "
                "(SELECT COUNT(*) FROM information_schema.events "
                "WHERE event_schema=DATABASE()) + "
                "(SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema=DATABASE() AND engine <> 'InnoDB')",
            )
            if objects != "0":
                raise ValueError("Recovery supports InnoDB base tables only")
            revisions = self.query(
                arguments, directory, "SELECT version_num FROM alembic_version"
            ).splitlines()
            if len(revisions) != 1 or not revisions[0]:
                raise ValueError("Recovery requires one schema revision")
            sql_file = directory / "snapshot.sql"
            self.run_file(
                [
                    self.settings.dump_executable,
                    *arguments,
                    (
                        "--single-transaction"
                        if self.settings.consistency == "online"
                        else "--lock-all-tables"
                    ),
                    "--skip-comments",
                    "--skip-add-drop-table",
                    "--skip-triggers",
                    "--no-tablespaces",
                    "--set-gtid-purged=OFF",
                    self.database_name,
                ],
                sql_file,
                self.settings.max_sql_bytes,
            )
            sql = sql_file.read_text()
            current_revision = self.query(
                arguments, directory, "SELECT version_num FROM alembic_version"
            )
            if current_revision != revisions[0]:
                raise ValueError("Schema changed during backup; repeat it")
        return DatabaseSnapshot(sql=sql, schema_revision=revisions[0])

    def restore_empty(self, sql: str, revision: str) -> RestoreResult:
        if len(sql.encode()) > self.settings.max_sql_bytes:
            raise ValueError("SQL snapshot exceeds configured capacity")
        with self.connection_files() as (arguments, directory):
            count = self.query(
                arguments,
                directory,
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema=DATABASE()",
            )
            if count != "0":
                raise ValueError("Restore target must be an empty database")
            sql_file = directory / "restore.sql"
            sql_file.write_text(sql)
            with sql_file.open("rb") as stream:
                self.run(
                    [
                        self.settings.mysql_executable,
                        *arguments,
                        "--binary-mode=1",
                        "--local-infile=0",
                        "--skip-reconnect",
                        self.database_name,
                    ],
                    stdin=stream,
                    stdout=subprocess.DEVNULL,
                )
            restored_revision = self.query(
                arguments, directory, "SELECT version_num FROM alembic_version"
            )
            if restored_revision != revision:
                raise ValueError("Restored schema revision does not match")
            restored_tables = int(
                self.query(
                    arguments,
                    directory,
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema=DATABASE()",
                )
            )
        return RestoreResult(
            schema_revision=restored_revision, table_count=restored_tables
        )


def _option(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Invalid MySQL credential")
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )
    return '"' + escaped + '"'
