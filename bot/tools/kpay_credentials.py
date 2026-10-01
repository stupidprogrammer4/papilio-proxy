from __future__ import annotations

import asyncio
import getpass

from bot.core.config import Settings
from bot.infra.db.credentials import MysqlCredentialVault
from bot.models.credentials import KpayCredentials


async def _store(username: str, password: str) -> None:
    settings = Settings.from_environment(require_token=False)
    if settings.credential_encryption_key is None:
        raise SystemExit("CREDENTIAL_ENCRYPTION_KEY is required")
    vault = MysqlCredentialVault(settings.database_url, settings.credential_encryption_key)
    try:
        await vault.save_kpay_credentials(KpayCredentials(username, password))
    finally:
        await vault.close()


def main() -> None:
    print("KPay credentials are stored encrypted in MySQL. Input is not logged.")
    username = getpass.getpass("KPay mobile: ").strip()
    password = getpass.getpass("KPay password: ")
    if not username or not password:
        raise SystemExit("Both KPay credentials are required")
    try:
        asyncio.run(_store(username, password))
    finally:
        password = ""
    print("KPay credentials stored.")


if __name__ == "__main__":
    main()
