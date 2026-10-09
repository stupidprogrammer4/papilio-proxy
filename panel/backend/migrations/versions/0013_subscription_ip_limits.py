"""Add subscription-owned IP policies and source leases."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_subscription_ip_limits"
down_revision: str | None = "0012_automation_observations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
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
        "tbl_ip_limit_policies",
        *timestamps(),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_ips", sa.Integer(), nullable=False),
        sa.Column("lease_seconds", sa.Integer(), nullable=False),
        sa.Column("ban_seconds", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
    )
    op.create_table(
        "tbl_ip_sessions",
        *timestamps(),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("source_ip", sa.String(45), nullable=False),
        sa.Column(
            "last_node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
        ),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("blocked_until", sa.DateTime(), nullable=True),
        sa.Column("block_reason", sa.String(250), nullable=True),
        sa.Column(
            "blocked_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "subscription_id", "source_ip", name="uq_ip_session"
        ),
    )
    op.create_index(
        "ix_ip_session_activity",
        "tbl_ip_sessions",
        ["subscription_id", "expires_at"],
    )
    op.create_index(
        "ix_ip_session_block",
        "tbl_ip_sessions",
        ["subscription_id", "blocked_until"],
    )


def downgrade() -> None:
    op.drop_table("tbl_ip_sessions")
    op.drop_table("tbl_ip_limit_policies")
