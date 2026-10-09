"""Create customer identities for billing and subscriptions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_customers"
down_revision: str | None = "0002_staff"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_customers",
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
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "telegram_id", name="uq_tbl_customers_telegram_id"
        ),
    )


def downgrade() -> None:
    op.drop_table("tbl_customers")
