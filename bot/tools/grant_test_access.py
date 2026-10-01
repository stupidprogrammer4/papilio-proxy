"""Issue a private, zero-revenue pilot to a configured Telegram admin.

Example: python -m bot.tools.grant_test_access --mib 512 --days 1
"""

from __future__ import annotations

import argparse
import asyncio

from bot.core.config import Settings
from bot.infra.db.test_access import MysqlTestAccessRepository
from bot.services.test_access import TestAccessService


async def _grant(telegram_id: int | None, quota_mib: int, days: int) -> None:
    settings = Settings.from_environment(require_token=False)
    if telegram_id is None:
        if len(settings.admin_ids) != 1:
            raise SystemExit("Pass --telegram-id when zero or multiple admins are configured")
        telegram_id = next(iter(settings.admin_ids))
    repository = MysqlTestAccessRepository(settings.database_url)
    try:
        await repository.initialize()
        order_id = await TestAccessService(repository, settings.admin_ids).grant(
            telegram_id, quota_mib, days
        )
    finally:
        await repository.close()
    print(f"Private pilot queued: {order_id[:8]} ({quota_mib} MiB, {days} day(s))")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--telegram-id", type=int)
    parser.add_argument("--mib", type=int, default=512)
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(_grant(args.telegram_id, args.mib, args.days))


if __name__ == "__main__":
    main()
