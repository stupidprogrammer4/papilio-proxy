from __future__ import annotations

from bot.services.dashboard import DashboardSnapshot


def _size(value: int) -> str:
    return f"{value / 1024**3:.1f} GB"


def render(snapshot: DashboardSnapshot):
    from rich.align import Align
    from rich.columns import Columns
    from rich.panel import Panel
    from rich.table import Table

    cards = Columns(
        [
            Panel(Align.center(str(snapshot.users)), title="کاربران", border_style="cyan"),
            Panel(
                Align.center(str(snapshot.subscriptions)), title="اشتراک‌ها", border_style="magenta"
            ),
            Panel(Align.center(str(snapshot.active)), title="فعال", border_style="green"),
            Panel(
                Align.center(str(snapshot.pending)), title="در انتظار پرداخت", border_style="yellow"
            ),
            Panel(
                Align.center(f"{_size(snapshot.traffic_used)} / {_size(snapshot.traffic_limit)}"),
                title="مصرف ترافیک",
                border_style="blue",
            ),
        ],
        equal=True,
        expand=True,
    )

    users = Table(title="کاربران اخیر", expand=True, header_style="bold cyan")
    users.add_column("شناسه", justify="right")
    users.add_column("نام")
    users.add_column("نام کاربری")
    users.add_column("اشتراک", justify="center")
    for user_id, name, username, count in snapshot.recent_users:
        users.add_row(str(user_id), name, f"@{username}" if username else "—", str(count))

    subscriptions = Table(title="اشتراک‌های اخیر", expand=True, header_style="bold magenta")
    subscriptions.add_column("شناسه")
    subscriptions.add_column("کاربر")
    subscriptions.add_column("پلن")
    subscriptions.add_column("وضعیت")
    subscriptions.add_column("ترافیک", justify="left")
    for record_id, user_id, plan, state, used, limit in snapshot.subscriptions_rows:
        subscriptions.add_row(
            record_id[:8], str(user_id), plan, state, f"{_size(used)} / {_size(limit)}"
        )

    return Panel(
        Columns([users, subscriptions], equal=True, expand=True),
        title="Papilio • پنل مدیریت فقط‌خواندنی",
        subtitle="داده‌ها تغییر نمی‌کنند",
    ), cards
