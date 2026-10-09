"""Persist tiers and reversible purchase credit without changing sales."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044_customer_loyalty"
down_revision: str | None = "0043_balancer_policies"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def common() -> list[sa.Column]:
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
        "tbl_customer_tiers",
        *common(),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("minimum_bytes", sa.BigInteger(), nullable=False),
        sa.Column("discount_bps", sa.Integer(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "tbl_loyalty_policies",
        *common(),
        sa.Column("code", sa.String(32), nullable=False, unique=True),
        sa.Column("values_json", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "tbl_purchase_volumes",
        *common(),
        sa.Column("reference", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
        ),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("volume_bytes", sa.BigInteger(), nullable=False),
        sa.Column("purchase_count", sa.Integer(), nullable=False),
        sa.Column("paid_rial", sa.BigInteger(), nullable=False),
        sa.Column("commerce_json", sa.Text(), nullable=True),
        sa.Column(
            "reverses_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_purchase_volumes.id"),
            unique=True,
        ),
    )
    op.create_index(
        "ix_tbl_purchase_volumes_customer_id",
        "tbl_purchase_volumes",
        ["customer_id"],
    )
    op.create_index(
        "ix_tbl_purchase_volumes_subscription_id",
        "tbl_purchase_volumes",
        ["subscription_id"],
    )
    op.add_column("tbl_subscriptions", sa.Column("commerce_json", sa.Text()))


def downgrade() -> None:
    for table in (
        "tbl_purchase_volumes",
        "tbl_customer_tiers",
        "tbl_loyalty_policies",
    ):
        if (
            op.get_bind()
            .execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1"))
            .first()
            is not None
        ):
            raise RuntimeError("Restore a backup to preserve commerce history")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM tbl_subscriptions "
                "WHERE commerce_json IS NOT NULL LIMIT 1"
            )
        )
        .first()
        is not None
    ):
        raise RuntimeError("Restore a backup to preserve commerce history")
    op.drop_column("tbl_subscriptions", "commerce_json")
    op.drop_table("tbl_purchase_volumes")
    op.drop_table("tbl_loyalty_policies")
    op.drop_table("tbl_customer_tiers")
