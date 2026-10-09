"""Preserve one wallet debit per purchase request key."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_purchase_key"
down_revision: str | None = "0008_nodes"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"] for column in inspector.get_columns("tbl_subscriptions")
    }
    if "purchase_key" not in columns:
        op.add_column(
            "tbl_subscriptions",
            sa.Column("purchase_key", sa.String(128), nullable=True),
        )
    op.execute(
        "UPDATE tbl_subscriptions "
        "SET purchase_key = CONCAT('existing:', id) "
        "WHERE purchase_key IS NULL"
    )
    op.alter_column(
        "tbl_subscriptions",
        "purchase_key",
        existing_type=sa.String(128),
        nullable=False,
    )
    inspector = sa.inspect(op.get_bind())
    constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("tbl_subscriptions")
    }
    if "uq_tbl_subscriptions_purchase_key" not in constraints:
        op.create_unique_constraint(
            "uq_tbl_subscriptions_purchase_key",
            "tbl_subscriptions",
            ["purchase_key"],
        )


def downgrade() -> None:
    op.drop_constraint(
        "uq_tbl_subscriptions_purchase_key",
        "tbl_subscriptions",
        type_="unique",
    )
    op.drop_column("tbl_subscriptions", "purchase_key")
