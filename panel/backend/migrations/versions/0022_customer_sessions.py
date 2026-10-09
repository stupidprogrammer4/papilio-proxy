"""Add separate one-use customer links and revocable sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_customer_sessions"
down_revision: str | None = "0021_payment_destinations"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_customer_logins",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
    )
    op.create_table(
        "tbl_customer_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "customer_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_customers.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, index=True),
    )


def downgrade() -> None:
    op.drop_table("tbl_customer_sessions")
    op.drop_table("tbl_customer_logins")
