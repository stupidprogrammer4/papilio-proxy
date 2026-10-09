"""Retain the explicit suspension clock and selected staff context."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_subscription_suspension"
down_revision: str | None = "0023_private_receipts"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_subscriptions",
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("suspension_clock", sa.String(16), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("suspension_reason", sa.String(250), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("suspended_by_staff_id", sa.BigInteger(), nullable=True),
    )
    op.create_foreign_key(
        "fk_subscription_suspended_staff",
        "tbl_subscriptions",
        "tbl_staff",
        ["suspended_by_staff_id"],
        ["id"],
    )
    op.create_table(
        "tbl_subscription_controls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("request_key", sa.String(128), unique=True, nullable=False),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
        sa.Column("clock", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("tbl_subscription_controls")
    op.drop_constraint(
        "fk_subscription_suspended_staff",
        "tbl_subscriptions",
        type_="foreignkey",
    )
    op.drop_column("tbl_subscriptions", "suspended_by_staff_id")
    op.drop_column("tbl_subscriptions", "suspension_reason")
    op.drop_column("tbl_subscriptions", "suspension_clock")
    op.drop_column("tbl_subscriptions", "suspended_at")
