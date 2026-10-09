"""Create wallet ledger and manually approved top-up requests."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_wallet"
down_revision: str | None = "0003_customers"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tbl_wallets",
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
        ),
        sa.Column("balance_rial", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("customer_id", name="uq_tbl_wallets_customer_id"),
    )
    op.create_table(
        "tbl_wallet_entries",
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
            "wallet_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_wallets.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_rial", sa.BigInteger(), nullable=False),
        sa.Column("reference", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.UniqueConstraint(
            "reference", name="uq_tbl_wallet_entries_reference"
        ),
    )
    op.create_table(
        "tbl_topups",
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
        sa.Column("amount_rial", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("bank_reference", sa.String(128), nullable=True),
        sa.Column(
            "approved_by_staff_id",
            sa.BigInteger(),
            sa.ForeignKey("tbl_staff.id"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "bank_reference", name="uq_tbl_topups_bank_reference"
        ),
    )


def downgrade() -> None:
    op.drop_table("tbl_topups")
    op.drop_table("tbl_wallet_entries")
    op.drop_table("tbl_wallets")
