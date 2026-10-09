"""Create billable subscriptions with opt-in renewal state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_subscriptions"
down_revision: str | None = "0004_wallet"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_subscriptions",
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
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "plan_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_plans.id"),
            nullable=False,
        ),
        sa.Column("quota_bytes", sa.BigInteger(), nullable=False),
        sa.Column("price_rial", sa.BigInteger(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("auto_renew", sa.Boolean(), nullable=False),
        sa.Column("renewal_count", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("tbl_subscriptions")
