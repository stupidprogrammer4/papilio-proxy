"""Preserve purchased concurrency separately from operational overrides."""

import sqlalchemy as sa
from alembic import op

revision = "0055_purchased_ip_policy"
down_revision = "0054_managed_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tbl_purchased_ip_policies",
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
        sa.Column(
            "subscription_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_subscriptions.id"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_plans.id"),
            nullable=True,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("policy_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "subscription_id", name="uq_purchased_ip_subscription"
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT COUNT(*) FROM tbl_purchased_ip_policies")
    ):
        raise RuntimeError(
            "Downgrade would lose purchased IP policy snapshots"
        )
    op.drop_table("tbl_purchased_ip_policies")
