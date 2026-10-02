from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from papilio_proxy.config.settings import Settings
from papilio_proxy.modules.accounts.admin.infra.repository import MysqlAdminWebRepository


async def _save(username: str, password: str) -> None:
    settings = Settings.from_environment(require_token=False)
    repository = MysqlAdminWebRepository(settings.database_url)
    try:
        await repository.initialize()
        await repository.set_password(username, password)
    finally:
        await repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Set a web admin password through a hidden prompt")
    parser.add_argument("username", help="Web admin username")
    args = parser.parse_args()
    first = getpass("New admin password: ")
    second = getpass("Repeat admin password: ")
    if first != second:
        raise SystemExit("Passwords do not match")
    try:
        asyncio.run(_save(args.username, first))
    finally:
        first = second = ""
    print("Admin password hash saved; existing web sessions revoked.")


if __name__ == "__main__":
    main()
