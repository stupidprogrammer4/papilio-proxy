"""Preserve original wallet payer and reseller billing decisions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_subscription_payers"
down_revision: str | None = "0032_reseller_catalog"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_subscriptions",
        sa.Column("payer_customer_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("reseller_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("reseller_agreement_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_subscriptions",
        sa.Column("reseller_billing_json", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_subscription_payer",
        "tbl_subscriptions",
        "tbl_customers",
        ["payer_customer_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_subscription_reseller",
        "tbl_subscriptions",
        "tbl_resellers",
        ["reseller_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_subscription_agreement",
        "tbl_subscriptions",
        "tbl_reseller_plans",
        ["reseller_agreement_id"],
        ["id"],
    )
    op.create_index(
        "ix_tbl_subscriptions_payer_customer_id",
        "tbl_subscriptions",
        ["payer_customer_id"],
    )
    op.create_index(
        "ix_tbl_subscriptions_reseller_id",
        "tbl_subscriptions",
        ["reseller_id"],
    )
    op.execute("UPDATE tbl_subscriptions SET payer_customer_id=customer_id")


def downgrade() -> None:
    op.drop_constraint(
        "fk_subscription_agreement", "tbl_subscriptions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_subscription_reseller", "tbl_subscriptions", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_subscription_payer", "tbl_subscriptions", type_="foreignkey"
    )
    op.drop_index("ix_tbl_subscriptions_reseller_id", "tbl_subscriptions")
    op.drop_index(
        "ix_tbl_subscriptions_payer_customer_id", "tbl_subscriptions"
    )
    op.drop_column("tbl_subscriptions", "reseller_billing_json")
    op.drop_column("tbl_subscriptions", "reseller_agreement_id")
    op.drop_column("tbl_subscriptions", "reseller_id")
    op.drop_column("tbl_subscriptions", "payer_customer_id")
