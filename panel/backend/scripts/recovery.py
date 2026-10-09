import argparse
import sys
from pathlib import Path

import yaml

from src.config.settings import PapilioSettings
from src.modules.operations.backups.app.archives import RecoveryArchives
from src.modules.operations.backups.domain.contracts import RecoverySettings
from src.modules.operations.backups.infra.mysql import MySQLRecovery
from src.modules.operations.backups.interfaces import IRecoveryArchives


def main() -> None:
    parser = argparse.ArgumentParser(description="Encrypted MySQL recovery")
    parser.add_argument("--recovery-config", required=True, type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--app-config", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("--archive", required=True, type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("--archive", required=True, type=Path)
    restore.add_argument("--target-config", required=True, type=Path)
    extract = commands.add_parser("extract-config")
    extract.add_argument("--archive", required=True, type=Path)
    extract.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        settings = RecoverySettings.model_validate(
            yaml.safe_load(arguments.recovery_config.read_text())
        )
        if arguments.key_file.stat().st_mode & 0o077:
            raise ValueError("Recovery key file must be private")
        archives: IRecoveryArchives = RecoveryArchives(
            settings, arguments.key_file.read_text().strip()
        )
        if arguments.command == "create":
            config_yaml = arguments.app_config.read_text()
            config = PapilioSettings.model_validate(
                yaml.safe_load(config_yaml)
            )
            assert config.db is not None
            payload = archives.create(
                MySQLRecovery(config.db.dsn, settings),
                config_yaml,
                arguments.output,
            )
            print(
                f"Encrypted backup created; schema {payload.schema_revision}"
            )
        elif arguments.command == "restore":
            config = PapilioSettings.model_validate(
                yaml.safe_load(arguments.target_config.read_text())
            )
            assert config.db is not None
            result = archives.restore(
                arguments.archive, MySQLRecovery(config.db.dsn, settings)
            )
            print(
                f"Restored schema {result.schema_revision}; "
                f"{result.table_count} tables"
            )
        elif arguments.command == "extract-config":
            archives.extract_config(arguments.archive, arguments.output)
            print(
                "Original private configuration extracted; review before use"
            )
        else:
            payload = archives.read(arguments.archive)
            print(
                f"Archive verified; schema {payload.schema_revision}; "
                f"created {payload.created_at.isoformat()}"
            )
    except Exception:
        print(
            "Recovery failed. Check key, capacities, private configuration, "
            "client availability and target state. Partial restores require "
            "a new empty target.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
