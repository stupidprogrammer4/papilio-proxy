"""Durable customer inbox and leased notification delivery."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_notifications"
down_revision: str | None = "0028_support_tickets"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def persistence() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "tbl_notifications",
        *persistence(),
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
        ),
        sa.Column("event_key", sa.String(160), nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("record_id", sa.BigInteger()),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("inbox_visible", sa.Boolean(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(32), nullable=False, index=True),
        sa.Column(
            "revision", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "retry_budget_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("next_attempt_at", sa.DateTime(), index=True),
        sa.Column("claim_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("error_code", sa.String(64)),
        sa.UniqueConstraint(
            "customer_id", "event_key", name="uq_notification_event"
        ),
    )
    op.create_table(
        "tbl_notification_attempts",
        *persistence(),
        sa.Column(
            "notification_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_notifications.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("finished_at", sa.DateTime()),
        sa.UniqueConstraint(
            "notification_id", "attempt", name="uq_notification_attempt"
        ),
    )
    op.create_table(
        "tbl_notification_recoveries",
        *persistence(),
        sa.Column(
            "notification_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_notifications.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("previous_status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(250), nullable=False),
        sa.UniqueConstraint(
            "notification_id", "revision", name="uq_notification_recovery"
        ),
    )


def downgrade() -> None:
    op.drop_table("tbl_notification_recoveries")
    op.drop_table("tbl_notification_attempts")
    op.drop_table("tbl_notifications")
