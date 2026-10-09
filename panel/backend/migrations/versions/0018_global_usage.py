"""Add durable counters and shared budgets without rewriting prior sales."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_global_usage"
down_revision: str | None = "0017_inbound_revisions"
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
    op.add_column(
        "tbl_plans", sa.Column("quota_policy_json", sa.Text(), nullable=True)
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("quota_policy_json", sa.Text(), nullable=True),
    )
    op.create_table(
        "tbl_usage_grants",
        *timestamps(),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "profile_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_profiles.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("configuration_revision", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("allocated_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "upload_bytes", sa.BigInteger(), nullable=False, server_default="0"
        ),
        sa.Column(
            "download_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "sequence", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "is_closed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("sampled_at", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint(
            "profile_id",
            "generation",
            "request_key",
            name="uq_usage_allocation",
        ),
    )
    op.create_table(
        "tbl_usage_events",
        *timestamps(),
        sa.Column(
            "grant_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_usage_grants.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("upload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("download_bytes", sa.BigInteger(), nullable=False),
        sa.Column("delta_upload_bytes", sa.BigInteger(), nullable=False),
        sa.Column("delta_download_bytes", sa.BigInteger(), nullable=False),
        sa.Column("delta_bytes", sa.BigInteger(), nullable=False),
        sa.Column("final", sa.Boolean(), nullable=False),
        sa.Column("sampled_at", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint("node_id", "event_id", name="uq_usage_event"),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a backup to roll back durable usage")
