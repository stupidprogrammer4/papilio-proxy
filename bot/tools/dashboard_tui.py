from __future__ import annotations

import argparse
import asyncio

from bot.core.config import Settings
from bot.infra.db.dashboard import MysqlDashboardRepository
from bot.services.dashboard import DashboardService
from bot.tools.admin_tui import render


async def run(watch_seconds: float | None) -> None:
    from rich.columns import Columns
    from rich.console import Console
    from rich.live import Live

    settings = Settings.from_environment(require_token=False)
    repository = MysqlDashboardRepository(settings.database_url)
    service = DashboardService(repository)
    console = Console()
    try:
        if watch_seconds is None:
            panel, cards = render(await service.snapshot())
            console.print(cards)
            console.print(panel)
            return
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                panel, cards = render(await service.snapshot())
                live.update(Columns([cards, panel]))
                await asyncio.sleep(watch_seconds)
    finally:
        await repository.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="پنل فقط‌خواندنی MySQL پاپیلیو")
    parser.add_argument(
        "--watch", type=float, metavar="SECONDS", help="refresh interval; no database writes"
    )
    args = parser.parse_args()
    if args.watch is not None and args.watch <= 0:
        parser.error("--watch باید بزرگ‌تر از صفر باشد")
    asyncio.run(run(args.watch))


if __name__ == "__main__":
    main()
