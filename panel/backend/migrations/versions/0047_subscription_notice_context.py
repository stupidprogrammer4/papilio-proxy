"""Preserve the first captured subscription alert context."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047_subscription_notice_context"
down_revision: str | None = "0046_core_memberships"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_notifications",
        sa.Column("subscription_context", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    count = op.get_bind().scalar(
        sa.text(
            "SELECT COUNT(*) FROM tbl_notifications "
            "WHERE subscription_context IS NOT NULL"
        )
    )
    if count:
        raise RuntimeError(
            "Downgrade would lose immutable subscription alert context"
        )
    op.drop_column("tbl_notifications", "subscription_context")
