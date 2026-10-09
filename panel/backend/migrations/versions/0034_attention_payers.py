"""Retain the observed renewal quote and original paying wallet."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_attention_payers"
down_revision: str | None = "0033_subscription_payers"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tbl_subscription_attention",
        sa.Column("payer_customer_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_subscription_attention",
        sa.Column("renewal_price_rial", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "tbl_subscription_attention",
        sa.Column("renewal_available", sa.Boolean(), nullable=True),
    )
    op.create_foreign_key(
        "fk_attention_payer",
        "tbl_subscription_attention",
        "tbl_customers",
        ["payer_customer_id"],
        ["id"],
    )
    op.create_index(
        "ix_tbl_subscription_attention_payer_customer_id",
        "tbl_subscription_attention",
        ["payer_customer_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_attention_payer", "tbl_subscription_attention", type_="foreignkey"
    )
    op.drop_index(
        "ix_tbl_subscription_attention_payer_customer_id",
        "tbl_subscription_attention",
    )
    op.drop_column("tbl_subscription_attention", "renewal_available")
    op.drop_column("tbl_subscription_attention", "renewal_price_rial")
    op.drop_column("tbl_subscription_attention", "payer_customer_id")
