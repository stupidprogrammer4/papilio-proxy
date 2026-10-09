"""Persist recoverable fulfillment without changing existing access."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_durable_fulfillment"
down_revision: str | None = "0015_dual_transport_reservations"
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
        "tbl_plans", sa.Column("fulfillment_json", sa.Text(), nullable=True)
    )
    op.add_column(
        "tbl_plans", sa.Column("ip_limit_json", sa.Text(), nullable=True)
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("fulfillment_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column(
            "provisioning_managed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column(
            "used_bytes", sa.BigInteger(), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column(
            "base_quota_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("activated_at", sa.DateTime(), nullable=True),
    )
    op.execute("UPDATE tbl_subscriptions SET base_quota_bytes=quota_bytes")
    op.add_column(
        "tbl_profiles",
        sa.Column("applied_generation", sa.Integer(), nullable=True),
    )
    op.create_table(
        "tbl_provision_requests",
        *timestamps(),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("deadline_at", sa.DateTime(), nullable=False),
        sa.Column("retry_reason", sa.String(250), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("cancellation_reason", sa.String(250), nullable=True),
        sa.Column(
            "cancelled_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "subscription_id", "generation", name="uq_provision_generation"
        ),
    )
    op.create_table(
        "tbl_provision_tasks",
        *timestamps(),
        sa.Column(
            "request_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_provision_requests.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "configuration_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_configurations.id"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_nodes.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("encrypted_payload", sa.Text(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claim_hash", sa.String(64), nullable=True),
        sa.Column("claim_until", sa.DateTime(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("last_outcome", sa.String(16), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=False, index=True),
        sa.UniqueConstraint(
            "request_id", "configuration_id", name="uq_provision_target"
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Restore a backup to roll back durable fulfillment")
