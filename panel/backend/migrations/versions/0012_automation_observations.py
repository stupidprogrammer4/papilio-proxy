"""Persist payment, node and subscription check results."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_automation_observations"
down_revision: str | None = "0011_query_indexes"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
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
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
    ]


def upgrade() -> None:
    op.create_table(
        "tbl_payment_reviews",
        *timestamps(),
        sa.Column(
            "topup_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_topups.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("competing_topup_count", sa.Integer(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False, index=True),
    )
    op.create_table(
        "tbl_node_health",
        *timestamps(),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("successful_count", sa.Integer(), nullable=False),
        sa.Column("average_latency_ms", sa.Integer(), nullable=True),
        sa.Column("last_sample_at", sa.DateTime(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=False, index=True),
    )
    op.create_table(
        "tbl_subscription_attention",
        *timestamps(),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("wallet_balance_rial", sa.BigInteger(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False, index=True),
    )
    op.create_index(
        "ix_probe_node_time", "tbl_probes", ["node_id", "sampled_at"]
    )
    op.create_index(
        "ix_wallet_entry_wallet_id", "tbl_wallet_entries", ["wallet_id", "id"]
    )
    op.create_index(
        "ix_topup_amount_status_id",
        "tbl_topups",
        ["amount_rial", "status", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_topup_amount_status_id", table_name="tbl_topups")
    op.drop_index("ix_wallet_entry_wallet_id", table_name="tbl_wallet_entries")
    op.drop_index("ix_probe_node_time", table_name="tbl_probes")
    op.drop_table("tbl_subscription_attention")
    op.drop_table("tbl_node_health")
    op.drop_table("tbl_payment_reviews")
